import threading
from datetime import datetime


# Pricing per 1M tokens (USD) — update as needed
MODEL_PRICING = {
    # GPT-5.1
    "gpt-5.1": {"input": 2.00, "output": 8.00},
    # GPT-5
    "gpt-5": {"input": 2.00, "output": 8.00},
    # GPT-4.1
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    # GPT-4o
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # Embedding
    "text-embedding-3-small": {"input": 0.02, "output": 0.00},
}

# Default fallback pricing
DEFAULT_PRICING = {"input": 5.00, "output": 15.00}


class APICostTracker:
    """Thread-safe singleton tracker for OpenAI API costs."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()
    
    def reset(self):
        """Reset all counters."""
        with self._lock:
            self.total_input_tokens = 0
            self.total_output_tokens = 0
            self.total_calls = 0
            self.per_model = {}  # model -> {input_tokens, output_tokens, calls}
            self.start_time = datetime.now()
    
    def track(self, response, model: str = None):
        """
        Track usage from an OpenAI API response.
        
        Parameters
        ----------
        response : OpenAI ChatCompletion response object
            The response from client.chat.completions.create()
        model : str, optional
            Model name override. If None, extracted from response.
        """
        if not response or not hasattr(response, 'usage') or not response.usage:
            return
        
        usage = response.usage
        input_tokens = getattr(usage, 'prompt_tokens', 0) or 0
        output_tokens = getattr(usage, 'completion_tokens', 0) or 0
        
        if model is None:
            model = getattr(response, 'model', 'unknown')
        
        with self._lock:
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_calls += 1
            
            if model not in self.per_model:
                self.per_model[model] = {'input_tokens': 0, 'output_tokens': 0, 'calls': 0}
            self.per_model[model]['input_tokens'] += input_tokens
            self.per_model[model]['output_tokens'] += output_tokens
            self.per_model[model]['calls'] += 1
    
    def _get_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for a model."""
        # Match model to pricing (handle versioned model names like 'gpt-5.1-2025-04-14')
        pricing = DEFAULT_PRICING
        for key, p in MODEL_PRICING.items():
            if model.startswith(key):
                pricing = p
                break
        
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost
    
    def get_total_cost(self) -> float:
        """Get total cost in USD."""
        with self._lock:
            total = 0.0
            for model, stats in self.per_model.items():
                total += self._get_cost(model, stats['input_tokens'], stats['output_tokens'])
            return total
    
    def print_summary(self):
        """Print a formatted cost summary."""
        with self._lock:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            
            print(f"\n{'='*70}")
            print(f"💰 API COST SUMMARY")
            print(f"{'='*70}")
            print(f"  Duration: {elapsed/60:.1f} min  |  Total API calls: {self.total_calls}")
            print(f"  Total tokens: {self.total_input_tokens:,} input + {self.total_output_tokens:,} output = {self.total_input_tokens + self.total_output_tokens:,}")
            
            if self.per_model:
                print(f"\n  {'Model':<30} {'Calls':>6} {'Input':>12} {'Output':>12} {'Cost':>10}")
                print(f"  {'-'*30} {'-'*6} {'-'*12} {'-'*12} {'-'*10}")
                
                grand_total = 0.0
                for model, stats in sorted(self.per_model.items()):
                    cost = self._get_cost(model, stats['input_tokens'], stats['output_tokens'])
                    grand_total += cost
                    print(f"  {model:<30} {stats['calls']:>6} {stats['input_tokens']:>12,} {stats['output_tokens']:>12,} ${cost:>8.4f}")
                
                print(f"  {'-'*30} {'-'*6} {'-'*12} {'-'*12} {'-'*10}")
                print(f"  {'TOTAL':<30} {self.total_calls:>6} {self.total_input_tokens:>12,} {self.total_output_tokens:>12,} ${grand_total:>8.4f}")
            
            print(f"{'='*70}\n")
    
    def get_summary_text(self) -> str:
        """Return summary as string (for logging to file)."""
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            self.print_summary()
        return f.getvalue()


# Global singleton
cost_tracker = APICostTracker()
