import os
import json
import time
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List


# ============================================================================
# DISK CACHE
# ============================================================================

class DiskCache:
    """
    Simple disk-based cache for LLM responses.

    Stores responses as JSON files keyed by SHA-256 hash of the prompt.
    This avoids redundant API calls for identical prompts (e.g., same
    pathway batch re-analyzed across runs).

    Cache directory: ~/.cache/pathway_analysis/llm_responses/
    """

    def __init__(self, cache_dir: Optional[str] = None):
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".cache" / "pathway_analysis" / "llm_responses"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            project_root = Path(__file__).resolve().parents[1]
            self.cache_dir = project_root / ".cache" / "llm_responses"
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    def _make_key(self, model: str, messages: list, temperature: float) -> str:
        """Generate a deterministic cache key from model + messages + temperature."""
        content = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, model: str, messages: list, temperature: float) -> Optional[str]:
        """Retrieve cached response if available."""
        key = self._make_key(model, messages, temperature)
        cache_file = self.cache_dir / f"{key}.json"

        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                self._hits += 1
                return data.get("response")
            except (json.JSONDecodeError, IOError):
                pass

        self._misses += 1
        return None

    def put(self, model: str, messages: list, temperature: float, response: str):
        """Store a response in cache."""
        key = self._make_key(model, messages, temperature)
        cache_file = self.cache_dir / f"{key}.json"

        try:
            with open(cache_file, 'w') as f:
                json.dump({
                    "model": model,
                    "temperature": temperature,
                    "response": response,
                    "cached_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }, f, indent=2)
        except IOError as e:
            print(f"   ⚠️  Cache write failed: {e}")

    @property
    def stats(self) -> Dict[str, int]:
        """Return cache hit/miss statistics."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate_pct": round(hit_rate, 1),
        }

    def clear(self):
        """Clear all cached responses."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        self._hits = 0
        self._misses = 0
        print(f"   🗑️  Cleared {count} cached responses")


# ============================================================================
# LLM CLIENT
# ============================================================================

class LLMClient:
    """
    Unified GPT interface for the pathway analysis pipeline.

    Features:
    - Disk-based response caching (identical prompts → cached response)
    - Retry logic with exponential backoff
    - Cost tracking via api_cost_tracker
    - JSON response parsing

    Usage:
        client = LLMClient(model="gpt-5.1")
        response = client.generate(
            system_prompt="You are a biomedical expert.",
            user_prompt="Rank these pathways...",
            max_tokens=2000
        )
        print(client.cache.stats)  # {'hits': 5, 'misses': 2, ...}
    """

    def __init__(
        self,
        model: str = "gpt-5.1",
        timeout: float = 120.0,
        enable_cache: bool = True,
        cache_dir: Optional[str] = None,
    ):
        """
        Initialize the LLM client.

        Parameters
        ----------
        model : str
            Default model name (can be overridden per call)
        timeout : float
            API request timeout in seconds
        enable_cache : bool
            Enable disk-based response caching (default: True)
        cache_dir : str, optional
            Custom cache directory path
        """
        self.default_model = model
        self.timeout = timeout
        self._client = None
        self._cost_tracker = None

        # Response cache
        self.enable_cache = enable_cache
        self.cache = DiskCache(cache_dir) if enable_cache else None

    @property
    def client(self):
        """Lazy-initialize the OpenAI client."""
        if self._client is None:
            from openai import OpenAI
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY environment variable not set."
                )
            self._client = OpenAI(api_key=api_key, timeout=self.timeout)
        return self._client

    @property
    def cost_tracker(self):
        """Lazy-initialize the cost tracker."""
        if self._cost_tracker is None:
            try:
                from api_cost_tracker import cost_tracker
                self._cost_tracker = cost_tracker
            except ImportError:
                self._cost_tracker = None
        return self._cost_tracker

    def generate(
        self,
        user_prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        retries: int = 3,
        retry_delay: float = 5.0,
        use_cache: bool = True,
    ) -> str:
        """
        Generate a response from the LLM.

        Parameters
        ----------
        user_prompt : str
            User message content
        system_prompt : str
            System message content
        model : str, optional
            Model to use (defaults to self.default_model)
        max_tokens : int
            Maximum completion tokens
        temperature : float
            Sampling temperature
        retries : int
            Number of retry attempts on failure
        retry_delay : float
            Seconds to wait between retries
        use_cache : bool
            Whether to use response cache for this call (default: True).
            Set to False for non-deterministic outputs.

        Returns
        -------
        str
            Raw text response from the LLM
        """
        model = model or self.default_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # ── Check cache ──
        if use_cache and self.cache is not None:
            cached = self.cache.get(model, messages, temperature)
            if cached is not None:
                return cached

        # ── API call with retries ──
        last_error = None
        for attempt in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_completion_tokens=max_tokens,
                    temperature=temperature,
                )
                # Track cost
                if self.cost_tracker:
                    self.cost_tracker.track(response)

                result = response.choices[0].message.content.strip()

                # ── Store in cache ──
                if use_cache and self.cache is not None:
                    self.cache.put(model, messages, temperature, result)

                return result

            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    wait = retry_delay * (2 ** attempt)  # Exponential backoff
                    print(f"   ⚠️  LLM call failed (attempt {attempt + 1}/{retries}): {e}")
                    print(f"   ⏳  Retrying in {wait:.0f}s...")
                    time.sleep(wait)

        raise RuntimeError(
            f"LLM call failed after {retries} attempts: {last_error}"
        )

    def generate_json(
        self,
        user_prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.3,
        use_cache: bool = True,
    ) -> Any:
        """
        Generate a response and parse it as JSON.

        Parameters
        ----------
        user_prompt : str
            User message (should instruct model to output JSON)
        system_prompt : str
            System message
        model : str, optional
            Model to use
        max_tokens : int
            Maximum completion tokens
        temperature : float
            Sampling temperature (lower for structured output)
        use_cache : bool
            Whether to use response cache

        Returns
        -------
        Parsed JSON object (dict, list, etc.)

        Raises
        ------
        json.JSONDecodeError
            If the response cannot be parsed as JSON
        """
        raw = self.generate(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            use_cache=use_cache,
        )

        # Try to extract JSON from the response
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        return json.loads(text)

    def compute_embeddings(
        self,
        texts: List[str],
        model: str = "text-embedding-3-small"
    ) -> List[List[float]]:
        """
        Compute embeddings for a list of texts.

        Parameters
        ----------
        texts : List[str]
            Texts to embed
        model : str
            Embedding model name

        Returns
        -------
        List of embedding vectors
        """
        response = self.client.embeddings.create(input=texts, model=model)
        if self.cost_tracker:
            self.cost_tracker.track(response)
        return [item.embedding for item in response.data]

    def print_cache_stats(self):
        """Print cache hit/miss statistics."""
        if self.cache:
            stats = self.cache.stats
            print(f"   📊 LLM Cache Stats: "
                  f"{stats['hits']} hits / {stats['misses']} misses "
                  f"({stats['hit_rate_pct']}% hit rate)")
        else:
            print("   ℹ️  LLM cache disabled")
