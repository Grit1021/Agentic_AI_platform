import os
import sys

# OpenAI API Key should be set in environment before running
if 'OPENAI_API_KEY' not in os.environ:
    print("⚠️  Warning: OPENAI_API_KEY not set in environment")
    print("   Set it with: export OPENAI_API_KEY='your-key'")

# PyTorch 2.2.2 Compatible Agent Loader
try:
    from agents_loader_pytorch_compat import (
        load_agents_pytorch_compat,
        check_pytorch_version,
        restore_original_db_utils
    )
    AGENTS_LOADER_AVAILABLE = True
except ImportError:
    # Module doesn't exist - will use direct agent imports in __init__
    AGENTS_LOADER_AVAILABLE = False


class MultiAgentPathwayAnalyzer:
    """
    Multi-Agent System for pathway analysis.
    
    Simplified version that only initializes the four agents:
    - PlanningAgent: Pathway enrichment (g:Profiler) + PubMed ranking
    - QueryAgent: Information retrieval
    - ReasoningAgent: Pathway interpretation + PPI analysis
    - WritingAgent: Report generation
    """
    
    def __init__(self, output_dir, model="gpt-5.1", use_pytorch_compat=True):
        """
        Initialize Multi-Agent system.
        
        Parameters:
        -----------
        output_dir : str
            Output directory for results
        model : str
            LLM model to use (default: gpt-5.1)
        use_pytorch_compat : bool
            Use PyTorch-compatible MySQL package (default: True)
        """
        self.output_dir = output_dir
        self.model = model
        
        # Create output directories
        self.results_dir = os.path.join(output_dir, 'multi_agent_analysis')
        self.imgs_dir = os.path.join(self.results_dir, 'imgs')
        os.makedirs(self.results_dir, exist_ok=True)
        os.makedirs(self.imgs_dir, exist_ok=True)
        
        # Check PyTorch version (only if agents_loader module is available)
        if use_pytorch_compat and AGENTS_LOADER_AVAILABLE:
            check_pytorch_version()
        
        # Initialize agents (default to None; set properly if loading succeeds)
        self.agents_ready = False
        self.planning_agent = None
        self.reasoning_agent = None
        self.writing_agent = None
        self.query_agent = None
        
        if use_pytorch_compat and AGENTS_LOADER_AVAILABLE:
            print("\n" + "="*80)
            print("INITIALIZING MULTI-AGENT SYSTEM (PyTorch 2.2.2 Compatible)")
            print("="*80)
            
            success, planning_agent, reasoning_agent, writing_agent, query_agent = \
                load_agents_pytorch_compat(model=model)
            
            if success:
                self.planning_agent = planning_agent
                self.reasoning_agent = reasoning_agent
                self.writing_agent = writing_agent
                self.query_agent = query_agent
                self.agents_ready = True
            else:
                print("\n" + "="*80)
                print("⚠️  AGENTS NOT AVAILABLE")
                print("="*80)
                print("Multi-Agent analysis will be skipped.")
                print("\n💡 Required packages:")
                print("   pip install pymysql sqlalchemy pandas numpy")
                print("   pip install openai anthropic")
        elif use_pytorch_compat and not AGENTS_LOADER_AVAILABLE:
            # Legacy loading (may have PyTorch compatibility issues)
            print("\n⚠️  Using legacy agent loading (may have PyTorch compatibility issues)")
            
            try:
                DEMO_SRC_PATH = "/Users/liyuxin/Documents/zotero/PhD/Research/AI_agent/codes/Biomedical-AI-Agent-revision-less-hallucination/src"
                if DEMO_SRC_PATH not in sys.path:
                    sys.path.insert(0, DEMO_SRC_PATH)
                
                from agents.ReasoningAgent import ReasoningAgent
                from agents.PlanningAgent import PlanningAgent
                from agents.WrittingAgent import WrittingAgent
                from agents.QueryAgent import QueryAgent
                
                self.planning_agent = PlanningAgent(model=model)
                self.reasoning_agent = ReasoningAgent(model=model)
                self.writing_agent = WrittingAgent(model=model)
                self.query_agent = QueryAgent(model=model)
                self.agents_ready = True
                
            except Exception as e:
                print(f"❌ Error loading agents: {e}")
                self.agents_ready = False
        
        print(f"\n📁 Results will be saved in: {self.results_dir}")
        if self.agents_ready:
            print("✅ All agents initialized successfully")
        else:
            print("⚠️  Agents not available - multi-agent analysis disabled")
