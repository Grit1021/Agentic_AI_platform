import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np


class PathwayMemoryBank:
    """
    Memory bank for storing and retrieving pathway analysis experiences.
    
    Features:
    - Store pathway predictions with disease context
    - Retrieve similar disease experiences for transfer learning
    - Track disease-pathway associations across analyses
    - Store GPT reasoning patterns for future reference
    - Export knowledge graphs and summaries
    """
    
    def __init__(self, db_path: str = "pathway_knowledge.db"):
        """
        Initialize the pathway memory bank.
        
        Parameters:
        -----------
        db_path : str
            Path to SQLite database file
        """
        self.db_path = db_path
        self.conn = None
        self._initialize_database()
    
    def _initialize_database(self):
        """Create database tables if they don't exist."""
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()
        
        # Table 1: Diseases analyzed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diseases (
                mesh_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                analyzed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                num_modules INTEGER,
                total_pathways INTEGER,
                avg_pathway_rank REAL,
                metadata TEXT
            )
        """)
        
        # Table 2: Pathway experiences (individual predictions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pathway_experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mesh_id TEXT NOT NULL,
                disease_name TEXT NOT NULL,
                module_id INTEGER,
                iteration INTEGER,
                pathway_name TEXT NOT NULL,
                pathway_source TEXT,
                pathway_description TEXT,
                gpt_rank INTEGER,
                p_value REAL,
                num_pubmed_papers INTEGER,
                gpt_reasoning TEXT,
                success_score REAL,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (mesh_id) REFERENCES diseases(mesh_id)
            )
        """)
        
        # Table 3: Disease-pathway associations (aggregated)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS disease_pathway_associations (
                disease_mesh_id TEXT,
                pathway_name TEXT,
                pathway_source TEXT,
                evidence_count INTEGER DEFAULT 1,
                avg_rank REAL,
                best_rank INTEGER,
                avg_p_value REAL,
                first_seen_date TIMESTAMP,
                last_seen_date TIMESTAMP,
                PRIMARY KEY (disease_mesh_id, pathway_name),
                FOREIGN KEY (disease_mesh_id) REFERENCES diseases(mesh_id)
            )
        """)
        
        
        # Create indexes for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pathway_exp_disease 
            ON pathway_experiences(mesh_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pathway_exp_name 
            ON pathway_experiences(pathway_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pathway_exp_rank 
            ON pathway_experiences(gpt_rank)
        """)
        
        # Table 5: Pathway embeddings for Semantic RAG
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pathway_embeddings (
                experience_id INTEGER PRIMARY KEY,
                embedding BLOB,
                embedding_text TEXT,
                model_name TEXT DEFAULT 'text-embedding-3-small',
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (experience_id) REFERENCES pathway_experiences(id)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_embedding_model
            ON pathway_embeddings(model_name)
        """)
        
        self.conn.commit()
        print(f"✅ Memory Bank initialized: {self.db_path}")
    
    def store_disease_analysis(
        self,
        disease_id: str,
        disease_name: str,
        description: str,
        num_modules: int,
        total_pathways: int,
        category: Optional[str] = None,
        metadata: Optional[Dict] = None
    ):
        """
        Store high-level disease analysis information.
        
        Parameters:
        -----------
        disease_id : str
            MeSH ID of the disease
        disease_name : str
            Full disease name
        description : str
            Disease description
        num_modules : int
            Number of modules analyzed
        total_pathways : int
            Total pathways identified
        category : str, optional
            Disease category (e.g., 'neurodegenerative', 'metabolic')
        metadata : dict, optional
            Additional metadata
        """
        cursor = self.conn.cursor()
        
        metadata_json = json.dumps(metadata) if metadata else None
        
        cursor.execute("""
            INSERT OR REPLACE INTO diseases 
            (mesh_id, name, description, category, num_modules, total_pathways, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (disease_id, disease_name, description, category, num_modules, 
              total_pathways, metadata_json))
        
        self.conn.commit()
        print(f"  💾 Stored disease analysis: {disease_name} ({disease_id})")
    
    def store_pathway_experience(
        self,
        disease_id: str,
        pathway_data: Dict[str, Any],
        iteration_context: Dict[str, Any]
    ):
        """
        Store a single pathway prediction experience.
        
        Parameters:
        -----------
        disease_id : str
            MeSH ID of the disease
        pathway_data : dict
            Pathway information including name, description, rank, etc.
        iteration_context : dict
            Analysis context (module_id, iteration, etc.)
        """
        cursor = self.conn.cursor()
        
        # Extract pathway information
        pathway_name = pathway_data.get('name', '')
        pathway_source = pathway_data.get('source', '')
        pathway_desc = pathway_data.get('description', '')
        gpt_rank = pathway_data.get('gpt_rank', None)
        p_value = pathway_data.get('p_value', None)
        
        gpt_reasoning = pathway_data.get('gpt_reasoning', '')
        
        # Calculate success score based on rank and p-value
        # Note: gpt_rank already incorporates PubMed literature as one of its 4 ranking dimensions,
        # so a separate literature component would be redundant.
        success_score = self._calculate_success_score(gpt_rank, p_value)
        
        # Extract iteration context
        module_id = iteration_context.get('module_id', None)
        iteration = iteration_context.get('iteration', None)
        disease_name = iteration_context.get('disease_name', '')
        
        # Store metadata
        metadata = {
            'total_candidates': iteration_context.get('total_candidates', 0),
            'pathway_category': pathway_source
        }
        metadata_json = json.dumps(metadata)
        
        cursor.execute("""
            INSERT INTO pathway_experiences 
            (mesh_id, disease_name, module_id, iteration, pathway_name, 
             pathway_source, pathway_description, gpt_rank, p_value, 
             gpt_reasoning, success_score, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (disease_id, disease_name, module_id, iteration, pathway_name,
              pathway_source, pathway_desc, gpt_rank, p_value,
              gpt_reasoning, success_score, metadata_json))
        
        self.conn.commit()
        
        # Update disease-pathway association
        self._update_disease_pathway_association(
            disease_id, pathway_name, pathway_source, gpt_rank, p_value
        )
    
    def _calculate_success_score(
        self, 
        gpt_rank: Optional[int], 
        p_value: Optional[float]
    ) -> float:
        """
        Calculate a success score for a pathway prediction.
        
        Score components (2 dimensions):
        - Rank quality (60%): Lower rank = higher score.
          gpt_rank already incorporates PubMed literature as one of its
          4 ranking dimensions, so a separate literature term is unnecessary.
        - Statistical significance (40%): Lower p-value = higher score.
        
        Returns score in range [0, 1]
        """
        score = 0.0
        
        # Rank component (60% weight)
        # gpt_rank synthesizes: pathway description, disease pathology,
        # p-value significance, and PubMed literature support.
        if gpt_rank is not None:
            rank_score = max(0, 1 - (gpt_rank / 100.0))  # Normalize to 0-1
            score += 0.6 * rank_score
        
        # P-value component (40% weight)
        if p_value is not None and p_value > 0:
            # Convert p-value to score: very small p-value = high score
            p_score = min(1.0, -np.log10(p_value) / 10.0)
            score += 0.4 * p_score
        
        return round(score, 3)
    
    def _update_disease_pathway_association(
        self,
        disease_id: str,
        pathway_name: str,
        pathway_source: str,
        rank: Optional[int],
        p_value: Optional[float]
    ):
        """Update aggregated disease-pathway association statistics."""
        cursor = self.conn.cursor()
        
        # Check if association exists
        cursor.execute("""
            SELECT evidence_count, avg_rank, best_rank, avg_p_value
            FROM disease_pathway_associations
            WHERE disease_mesh_id = ? AND pathway_name = ?
        """, (disease_id, pathway_name))
        
        row = cursor.fetchone()
        
        if row:
            # Update existing association
            count, avg_rank, best_rank, avg_p = row
            new_count = count + 1
            
            # Update averages
            if rank is not None:
                if avg_rank is not None:
                    new_avg_rank = (avg_rank * count + rank) / new_count
                else:
                    new_avg_rank = rank
                new_best_rank = min(best_rank, rank) if best_rank is not None else rank
            else:
                new_avg_rank = avg_rank
                new_best_rank = best_rank
            
            if p_value is not None:
                new_avg_p = (avg_p * count + p_value) / new_count if avg_p is not None else p_value
            else:
                new_avg_p = avg_p
            
            cursor.execute("""
                UPDATE disease_pathway_associations
                SET evidence_count = ?,
                    avg_rank = ?,
                    best_rank = ?,
                    avg_p_value = ?,
                    last_seen_date = CURRENT_TIMESTAMP
                WHERE disease_mesh_id = ? AND pathway_name = ?
            """, (new_count, new_avg_rank, new_best_rank, new_avg_p, 
                  disease_id, pathway_name))
        else:
            # Create new association
            cursor.execute("""
                INSERT INTO disease_pathway_associations
                (disease_mesh_id, pathway_name, pathway_source, evidence_count,
                 avg_rank, best_rank, avg_p_value, first_seen_date, last_seen_date)
                VALUES (?, ?, ?, 1, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (disease_id, pathway_name, pathway_source, rank, rank, p_value))
        
        self.conn.commit()
    
    def retrieve_similar_disease_experiences(
        self, 
        disease_id: str,
        disease_description: str = "",
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Retrieve experiences from similar diseases for transfer learning.
        
        Parameters:
        -----------
        disease_id : str
            Current disease MeSH ID
        disease_description : str
            Disease description for semantic matching
        top_k : int
            Number of similar diseases to retrieve
        
        Returns:
        --------
        List of dicts containing similar disease information and their top pathways
        """
        cursor = self.conn.cursor()
        
        # For now, use simple approach: retrieve all other diseases
        # TODO: Implement MeSH tree distance for better similarity
        cursor.execute("""
            SELECT mesh_id, name, description, category, num_modules, total_pathways
            FROM diseases
            WHERE mesh_id != ?
            ORDER BY analyzed_date DESC
            LIMIT ?
        """, (disease_id, top_k))
        
        similar_diseases = []
        for row in cursor.fetchall():
            mesh_id, name, desc, category, num_modules, total_pathways = row
            
            # Get top pathways for this disease
            cursor.execute("""
                SELECT pathway_name, pathway_source, avg_rank, evidence_count, avg_p_value
                FROM disease_pathway_associations
                WHERE disease_mesh_id = ?
                ORDER BY avg_rank
                LIMIT 20
            """, (mesh_id,))
            
            top_pathways = [
                {
                    'name': pw_name,
                    'source': pw_source,
                    'avg_rank': avg_rank,
                    'evidence_count': count,
                    'avg_p_value': avg_p
                }
                for pw_name, pw_source, avg_rank, count, avg_p in cursor.fetchall()
            ]
            
            similar_diseases.append({
                'mesh_id': mesh_id,
                'name': name,
                'description': desc,
                'category': category,
                'num_modules': num_modules,
                'total_pathways': total_pathways,
                'top_pathways': top_pathways
            })
        
        return similar_diseases
    
    def retrieve_pathway_knowledge(
        self,
        pathway_name: str,
        disease_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve historical knowledge about a specific pathway.
        
        Parameters:
        -----------
        pathway_name : str
            Name of the pathway
        disease_context : str, optional
            Disease MeSH ID to filter context
        
        Returns:
        --------
        Dict with pathway knowledge including past occurrences, average rank, etc.
        """
        cursor = self.conn.cursor()
        
        # Get all experiences with this pathway
        if disease_context:
            cursor.execute("""
                SELECT mesh_id, disease_name, gpt_rank, p_value, success_score
                FROM pathway_experiences
                WHERE pathway_name = ? AND mesh_id != ?
                ORDER BY success_score DESC
                LIMIT 10
            """, (pathway_name, disease_context))
        else:
            cursor.execute("""
                SELECT mesh_id, disease_name, gpt_rank, p_value, success_score
                FROM pathway_experiences
                WHERE pathway_name = ?
                ORDER BY success_score DESC
                LIMIT 10
            """, (pathway_name,))
        
        experiences = []
        for row in cursor.fetchall():
            mesh_id, disease_name, rank, p_val, score = row
            experiences.append({
                'disease_id': mesh_id,
                'disease_name': disease_name,
                'rank': rank,
                'p_value': p_val,
                'success_score': score
            })
        
        # Calculate statistics
        if experiences:
            ranks = [e['rank'] for e in experiences if e['rank'] is not None]
            avg_rank = np.mean(ranks) if ranks else None
            best_rank = min(ranks) if ranks else None
            num_diseases = len(set(e['disease_id'] for e in experiences))
        else:
            avg_rank = None
            best_rank = None
            num_diseases = 0
        
        return {
            'pathway_name': pathway_name,
            'num_occurrences': len(experiences),
            'num_diseases': num_diseases,
            'avg_rank': avg_rank,
            'best_rank': best_rank,
            'experiences': experiences
        }
    
    def get_gpt_reasoning_examples(
        self,
        pathway_category: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve GPT reasoning examples for a pathway category.
        
        Useful for few-shot prompting and understanding ranking patterns.
        
        Parameters:
        -----------
        pathway_category : str
            Pathway source (GO:BP, KEGG, etc.)
        limit : int
            Maximum number of examples
        
        Returns:
        --------
        List of reasoning examples with context
        """
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT pathway_name, disease_name, gpt_rank, gpt_reasoning, success_score
            FROM pathway_experiences
            WHERE pathway_source = ? 
              AND gpt_reasoning IS NOT NULL 
              AND gpt_reasoning != ''
            ORDER BY success_score DESC
            LIMIT ?
        """, (pathway_category, limit))
        
        examples = []
        for row in cursor.fetchall():
            pw_name, disease, rank, reasoning, score = row
            examples.append({
                'pathway': pw_name,
                'disease': disease,
                'rank': rank,
                'reasoning': reasoning,
                'success_score': score
            })
        
        return examples
    
    def retrieve_strategic_context(
        self, 
        challenge_description: str = "",
        pathway_category: Optional[str] = None,
        top_k: int = 3,
        min_success_score: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Retrieve top reasoning strategies from successful analyses for Reasoning RAG.
        
        This method supports Strategy B (Reasoning RAG) by extracting qualitative
        reasoning patterns that have led to successful predictions in past analyses.
        
        Parameters:
        -----------
        challenge_description : str
            Description of current challenge (e.g., "low validation rate", 
            "generic pathway predictions"). Used for future semantic search.
        pathway_category : str, optional
            Filter by pathway source (GO:BP, GO:MF, GO:CC, KEGG, REAC)
        top_k : int
            Number of top strategies to return (default: 3)
        min_success_score : float
            Minimum success score threshold (default: 0.5)
            
        Returns:
        --------
        List of dicts containing:
            - reasoning: The strategic reasoning text
            - success_score: How successful this strategy was
            - disease: The disease context where it succeeded
            - pathway: The pathway it was used for
            - pathway_source: Category of the pathway
        """
        cursor = self.conn.cursor()
        
        # Build query with optional category filter
        if pathway_category:
            cursor.execute("""
                SELECT DISTINCT gpt_reasoning, MAX(success_score) as max_score, 
                       disease_name, pathway_name, pathway_source
                FROM pathway_experiences
                WHERE gpt_reasoning IS NOT NULL 
                  AND gpt_reasoning != ''
                  AND pathway_source = ?
                  AND success_score >= ?
                GROUP BY gpt_reasoning
                ORDER BY max_score DESC
                LIMIT ?
            """, (pathway_category, min_success_score, top_k))
        else:
            cursor.execute("""
                SELECT DISTINCT gpt_reasoning, MAX(success_score) as max_score, 
                       disease_name, pathway_name, pathway_source
                FROM pathway_experiences
                WHERE gpt_reasoning IS NOT NULL 
                  AND gpt_reasoning != ''
                  AND success_score >= ?
                GROUP BY gpt_reasoning
                ORDER BY max_score DESC
                LIMIT ?
            """, (min_success_score, top_k))
        
        strategies = []
        for row in cursor.fetchall():
            reasoning, score, disease, pathway, source = row
            strategies.append({
                'reasoning': reasoning,
                'success_score': score,
                'disease': disease,
                'pathway': pathway,
                'pathway_source': source
            })
        
        # Log retrieval for debugging
        if strategies:
            print(f"📚 Retrieved {len(strategies)} strategic reasoning examples (min_score={min_success_score})")
            for i, s in enumerate(strategies, 1):
                print(f"   {i}. [{s['pathway_source']}] {s['reasoning'][:80]}... (score={s['success_score']:.3f})")
        else:
            print(f"⚠️  No strategic reasoning found (min_score={min_success_score})")
        
        return strategies
    
    def format_reasoning_for_injection(
        self,
        strategies: List[Dict[str, Any]]
    ) -> str:
        """
        Format retrieved strategies into a prompt-injectable string.
        
        Parameters:
        -----------
        strategies : List[Dict]
            Output from retrieve_strategic_context()
            
        Returns:
        --------
        Formatted string suitable for prompt injection
        """
        if not strategies:
            return ""
        
        lines = ["## Expert Reasoning Strategies (from successful past analyses):"]
        for i, s in enumerate(strategies, 1):
            lines.append(f"\n### Strategy {i} (validated in {s['disease']}):")
            lines.append(f"> {s['reasoning']}")
        
        lines.append("\n**Apply these strategies when analyzing the current gene set.**")
        
        return "\n".join(lines)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get overall memory bank statistics.
        
        Returns:
        --------
        Dict with statistics about stored knowledge
        """
        cursor = self.conn.cursor()
        
        # Count diseases
        cursor.execute("SELECT COUNT(*) FROM diseases")
        num_diseases = cursor.fetchone()[0]
        
        # Count pathway experiences
        cursor.execute("SELECT COUNT(*) FROM pathway_experiences")
        num_experiences = cursor.fetchone()[0]
        
        # Count unique pathways
        cursor.execute("SELECT COUNT(DISTINCT pathway_name) FROM pathway_experiences")
        num_unique_pathways = cursor.fetchone()[0]
        
        # Average pathways per disease
        avg_pathways_per_disease = num_experiences / num_diseases if num_diseases > 0 else 0
        
        # Get category distribution
        cursor.execute("""
            SELECT pathway_source, COUNT(*) as count
            FROM pathway_experiences
            GROUP BY pathway_source
            ORDER BY count DESC
        """)
        category_dist = {row[0]: row[1] for row in cursor.fetchall()}
        
        return {
            'num_diseases': num_diseases,
            'num_experiences': num_experiences,
            'num_unique_pathways': num_unique_pathways,
            'avg_pathways_per_disease': round(avg_pathways_per_disease, 2),
            'category_distribution': category_dist
        }
    
    def export_knowledge_summary(self, output_path: str):
        """
        Export a human-readable summary of the memory bank.
        
        Parameters:
        -----------
        output_path : str
            Path to output text file
        """
        stats = self.get_statistics()
        
        with open(output_path, 'w') as f:
            f.write("="*80 + "\n")
            f.write("PATHWAY MEMORY BANK KNOWLEDGE SUMMARY\n")
            f.write("="*80 + "\n\n")
            
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Database: {self.db_path}\n\n")
            
            f.write("OVERALL STATISTICS\n")
            f.write("-"*80 + "\n")
            f.write(f"  Total diseases analyzed: {stats['num_diseases']}\n")
            f.write(f"  Total pathway experiences: {stats['num_experiences']}\n")
            f.write(f"  Unique pathways: {stats['num_unique_pathways']}\n")
            f.write(f"  Avg pathways per disease: {stats['avg_pathways_per_disease']}\n\n")
            
            f.write("PATHWAY CATEGORY DISTRIBUTION\n")
            f.write("-"*80 + "\n")
            for category, count in stats['category_distribution'].items():
                f.write(f"  {category}: {count}\n")
            f.write("\n")
            
            # List all diseases
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT mesh_id, name, num_modules, total_pathways, analyzed_date
                FROM diseases
                ORDER BY analyzed_date DESC
            """)
            
            f.write("ANALYZED DISEASES\n")
            f.write("-"*80 + "\n")
            for row in cursor.fetchall():
                mesh_id, name, num_mod, num_pw, date = row
                f.write(f"  [{mesh_id}] {name}\n")
                f.write(f"    Modules: {num_mod} | Pathways: {num_pw} | Date: {date}\n\n")
        
        print(f"  📊 Knowledge summary exported to: {output_path}")
    
    def export_disease_pathway_network(self, output_path: str):
        """
        Export disease-pathway network as JSON for visualization.
        
        Parameters:
        -----------
        output_path : str
            Path to output JSON file
        """
        cursor = self.conn.cursor()
        
        # Get all disease-pathway associations
        cursor.execute("""
            SELECT disease_mesh_id, pathway_name, pathway_source, 
                   evidence_count, avg_rank, avg_p_value
            FROM disease_pathway_associations
            ORDER BY evidence_count DESC
        """)
        
        # Build network structure
        diseases = set()
        pathways = set()
        edges = []
        
        for row in cursor.fetchall():
            disease_id, pw_name, pw_source, count, avg_rank, avg_p = row
            diseases.add(disease_id)
            pathways.add(pw_name)
            
            edges.append({
                'source': disease_id,
                'target': pw_name,
                'evidence_count': count,
                'avg_rank': avg_rank,
                'avg_p_value': avg_p,
                'pathway_source': pw_source
            })
        
        # Get disease details
        disease_nodes = []
        for disease_id in diseases:
            cursor.execute("""
                SELECT name, category, num_modules, total_pathways
                FROM diseases
                WHERE mesh_id = ?
            """, (disease_id,))
            row = cursor.fetchone()
            if row:
                disease_nodes.append({
                    'id': disease_id,
                    'type': 'disease',
                    'name': row[0],
                    'category': row[1],
                    'num_modules': row[2],
                    'total_pathways': row[3]
                })
        
        # Pathway nodes
        pathway_nodes = [
            {'id': pw, 'type': 'pathway', 'name': pw}
            for pw in pathways
        ]
        
        network = {
            'nodes': disease_nodes + pathway_nodes,
            'edges': edges,
            'metadata': {
                'num_diseases': len(diseases),
                'num_pathways': len(pathways),
                'num_associations': len(edges),
                'generated': datetime.now().isoformat()
            }
        }
        
        with open(output_path, 'w') as f:
            json.dump(network, f, indent=2)
        
        print(f"  🕸️  Disease-pathway network exported to: {output_path}")
    
    # ========================================================================
    # SEMANTIC EMBEDDING RAG
    # ========================================================================
    
    def _get_openai_client(self):
        """Get or create OpenAI client for embeddings."""
        if not hasattr(self, '_openai_client'):
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        return self._openai_client
    
    def _compute_embedding(self, texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]:
        """
        Compute embeddings for a list of texts using OpenAI API.
        
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
        client = self._get_openai_client()
        # OpenAI batch limit is 2048 inputs
        response = client.embeddings.create(input=texts, model=model)
        return [item.embedding for item in response.data]
    
    def embed_all_experiences(
        self,
        model: str = "text-embedding-3-small",
        batch_size: int = 100,
        force_recompute: bool = False
    ) -> int:
        """
        Batch-embed all pathway experiences for semantic retrieval.
        
        Creates embeddings for text: "disease_name | pathway_source | pathway_name: description"
        
        Parameters
        ----------
        model : str
            Embedding model to use
        batch_size : int
            Number of texts per API call
        force_recompute : bool
            If True, re-embed even if embeddings already exist
            
        Returns
        -------
        int : Number of experiences embedded
        """
        cursor = self.conn.cursor()
        
        # Find experiences that need embedding
        if force_recompute:
            cursor.execute("""
                SELECT id, disease_name, pathway_source, pathway_name, pathway_description
                FROM pathway_experiences
            """)
        else:
            cursor.execute("""
                SELECT pe.id, pe.disease_name, pe.pathway_source, pe.pathway_name, pe.pathway_description
                FROM pathway_experiences pe
                LEFT JOIN pathway_embeddings emb ON pe.id = emb.experience_id
                WHERE emb.experience_id IS NULL
            """)
        
        rows = cursor.fetchall()
        if not rows:
            print("✅ All experiences already embedded")
            return 0
        
        print(f"🔄 Embedding {len(rows)} pathway experiences...")
        
        total_embedded = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            
            # Build embedding texts
            texts = []
            ids = []
            for row in batch:
                exp_id, disease, source, pw_name, pw_desc = row
                text = f"{disease} | {source} | {pw_name}: {pw_desc or pw_name}"
                texts.append(text[:8000])  # Truncate to model limit
                ids.append((exp_id, text))
            
            # Compute embeddings
            try:
                embeddings = self._compute_embedding(texts, model=model)
            except Exception as e:
                print(f"  ❌ Embedding batch {i//batch_size + 1} failed: {e}")
                continue
            
            # Store embeddings
            for (exp_id, text), emb_vector in zip(ids, embeddings):
                emb_bytes = np.array(emb_vector, dtype=np.float32).tobytes()
                cursor.execute("""
                    INSERT OR REPLACE INTO pathway_embeddings 
                    (experience_id, embedding, embedding_text, model_name)
                    VALUES (?, ?, ?, ?)
                """, (exp_id, emb_bytes, text, model))
            
            total_embedded += len(batch)
            if (i // batch_size + 1) % 10 == 0 or i + batch_size >= len(rows):
                print(f"  📊 Embedded {total_embedded}/{len(rows)} experiences")
                self.conn.commit()
        
        self.conn.commit()
        print(f"✅ Embedded {total_embedded} experiences total")
        return total_embedded
    
    def retrieve_by_semantic_similarity(
        self,
        query_text: str,
        pathway_category: Optional[str] = None,
        top_k: int = 10,
        min_success_score: float = 0.0,
        exclude_disease_id: Optional[str] = None,
        exclude_module_id: Optional[int] = None,
        include_disease_id: Optional[str] = None,
        model: str = "text-embedding-3-small"
    ) -> List[Dict[str, Any]]:
        """
        Retrieve pathway experiences by semantic similarity.
        
        Parameters
        ----------
        query_text : str
            Query text (e.g., "Obesity | GO:BP | genes: LEPR, FTO, MC4R...")
        pathway_category : str, optional
            Filter by pathway source (GO:BP, GO:MF, GO:CC, KEGG, REAC)
        top_k : int
            Number of results to return
        min_success_score : float
            Minimum success score filter
        exclude_disease_id : str, optional
            Exclude this disease (avoids data leakage)
        exclude_module_id : int, optional
            Exclude this module (for within-disease cross-module retrieval).
            When set, only the specified module is excluded, allowing experiences
            from other modules of the same disease to be retrieved.
        include_disease_id : str, optional
            Only include experiences from this disease (for intra-disease
            cross-module retrieval). When set, only experiences from the
            specified disease are considered.
        model : str
            Embedding model (must match stored embeddings)
            
        Returns
        -------
        List of dicts with pathway info and similarity score
        """
        cursor = self.conn.cursor()
        
        # Compute query embedding
        query_emb = np.array(self._compute_embedding([query_text], model=model)[0], dtype=np.float32)
        query_norm = np.linalg.norm(query_emb)
        if query_norm == 0:
            return []
        query_emb = query_emb / query_norm
        
        # Build filter query
        conditions = ["emb.embedding IS NOT NULL"]
        params = []
        
        if pathway_category:
            conditions.append("pe.pathway_source = ?")
            params.append(pathway_category)
        if min_success_score > 0:
            conditions.append("pe.success_score >= ?")
            params.append(min_success_score)
        if exclude_disease_id:
            conditions.append("pe.mesh_id != ?")
            params.append(exclude_disease_id)
        if include_disease_id:
            conditions.append("pe.mesh_id = ?")
            params.append(include_disease_id)
        if exclude_module_id is not None:
            conditions.append("pe.module_id != ?")
            params.append(exclude_module_id)
        
        where_clause = " AND ".join(conditions)
        
        cursor.execute(f"""
            SELECT pe.id, pe.disease_name, pe.mesh_id, pe.pathway_name, pe.pathway_source,
                   pe.pathway_description, pe.gpt_rank, pe.p_value, pe.success_score,
                   pe.module_id, pe.iteration, emb.embedding
            FROM pathway_experiences pe
            JOIN pathway_embeddings emb ON pe.id = emb.experience_id
            WHERE {where_clause}
        """, params)
        
        # Compute cosine similarities
        results = []
        for row in cursor.fetchall():
            exp_id, disease, mesh_id, pw_name, pw_source, pw_desc, rank, pval, score, mod_id, iteration, emb_bytes = row
            stored_emb = np.frombuffer(emb_bytes, dtype=np.float32)
            stored_norm = np.linalg.norm(stored_emb)
            if stored_norm == 0:
                continue
            similarity = float(np.dot(query_emb, stored_emb / stored_norm))
            
            results.append({
                'experience_id': exp_id,
                'disease_name': disease,
                'mesh_id': mesh_id,
                'pathway_name': pw_name,
                'pathway_source': pw_source,
                'pathway_description': pw_desc,
                'gpt_rank': rank,
                'p_value': pval,
                'success_score': score,
                'module_id': mod_id,
                'iteration': iteration,
                'similarity': similarity
            })
        
        # Sort by similarity and return top-k
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:top_k]
    
    def format_rag_context_for_generation(
        self,
        retrieved_experiences: List[Dict[str, Any]],
        max_items: int = 8
    ) -> str:
        """
        Format retrieved experiences as soft guidance for pathway generation.
        
        Designed to INSPIRE, not INSTRUCT — avoids the -62% problem
        from raw context injection.
        
        Parameters
        ----------
        retrieved_experiences : List[Dict]
            Output from retrieve_by_semantic_similarity()
        max_items : int
            Maximum items to include
            
        Returns
        -------
        Formatted string for injection into generation prompt
        """
        if not retrieved_experiences:
            return ""
        
        # Deduplicate by pathway name (keep highest similarity)
        seen_pathways = {}
        for exp in retrieved_experiences:
            pw = exp['pathway_name']
            if pw not in seen_pathways or exp['similarity'] > seen_pathways[pw]['similarity']:
                seen_pathways[pw] = exp
        
        unique_exps = sorted(seen_pathways.values(), key=lambda x: x['similarity'], reverse=True)[:max_items]
        
        # Separate validated vs failed
        validated = [e for e in unique_exps if e.get('p_value') and e['p_value'] < 0.05]
        failed = [e for e in unique_exps if not e.get('p_value') or e['p_value'] >= 0.05]
        
        lines = [
            "## Cross-Disease Pathway Insights (reference only — do NOT copy blindly)",
            "The following patterns were observed in analyses of SIMILAR disease modules.",
            "Use these as biological inspiration, not as instructions.",
            ""
        ]
        
        if validated:
            lines.append("**Frequently validated pathway types in similar contexts:**")
            for e in validated[:5]:
                pval_str = f"{e['p_value']:.2e}" if e['p_value'] else "N/A"
                lines.append(f"- [{e['pathway_source']}] \"{e['pathway_name']}\" "
                           f"(validated in {e['disease_name']}, p={pval_str})")
            lines.append("")
        
        if failed:
            lines.append("**Pathway types that tend to fail validation:**")
            for e in failed[:3]:
                lines.append(f"- [{e['pathway_source']}] \"{e['pathway_name']}\" "
                           f"(failed in {e['disease_name']})")
            lines.append("")
        
        lines.append("IMPORTANT: Prioritize disease-specific biological reasoning over these cross-disease patterns.")
        
        return "\n".join(lines)
    
    # ==========================================================================
    # Option B: Strategy Extraction (LLM-abstracted patterns)
    # ==========================================================================
    
    def extract_strategy_from_experiences(
        self,
        retrieved_experiences: List[Dict[str, Any]],
        disease_name: str,
        disease_description: str,
        model: str = "gpt-5.1",
        max_items: int = 15
    ) -> str:
        """
        Extract meta-level prediction guidance from retrieved experiences.
        
        Option B v2: Instead of abstract strategies ("pursue inflammatory signaling")
        or specific pathway names (Option A), this method extracts actionable
        meta-patterns about WHAT TYPES of predictions tend to validate.
        
        Design Philosophy:
        - Option A injects "WHAT worked" (specific pathway names) → too restrictive
        - Option B v1 injected "WHY it worked" (abstract strategies) → too vague
        - Option B v2 injects "HOW to predict better" (meta-level patterns) → actionable
          without constraining the exploration space
        
        The output is designed for injection into the USER PROMPT (not system prompt)
        to maximize LLM attention.
        
        Parameters
        ----------
        retrieved_experiences : List[Dict]
            Output from retrieve_by_semantic_similarity()
        disease_name : str
            Target disease name for contextual strategy
        disease_description : str
            Target disease description (truncated to 300 chars)
        model : str
            LLM model for strategy extraction (default: gpt-5.1)
        max_items : int
            Max experiences to feed into the abstraction prompt
            
        Returns
        -------
        str : Extracted meta-guidance text, or empty string if extraction fails
        """
        if not retrieved_experiences:
            return ""
        
        # Deduplicate by pathway name (keep highest similarity)
        seen_pathways = {}
        for exp in retrieved_experiences:
            pw = exp['pathway_name']
            if pw not in seen_pathways or exp['similarity'] > seen_pathways[pw]['similarity']:
                seen_pathways[pw] = exp
        
        unique_exps = sorted(
            seen_pathways.values(), 
            key=lambda x: x['similarity'], 
            reverse=True
        )[:max_items]
        
        # Separate validated vs failed
        validated = [e for e in unique_exps if e.get('p_value') and e['p_value'] < 0.05]
        failed = [e for e in unique_exps if not e.get('p_value') or e['p_value'] >= 0.05]
        
        if not validated and not failed:
            return ""
        
        # Compute data-driven statistics for the prompt
        # Classify by specificity (name length) and source
        from collections import Counter
        source_counts = Counter()
        source_validated = Counter()
        for e in unique_exps:
            source_counts[e['pathway_source']] += 1
            if e.get('p_value') and e['p_value'] < 0.05:
                source_validated[e['pathway_source']] += 1
        
        stats_lines = []
        for src in sorted(source_counts.keys()):
            total = source_counts[src]
            val = source_validated.get(src, 0)
            rate = val / total * 100 if total > 0 else 0
            stats_lines.append(f"  {src}: {val}/{total} validated ({rate:.0f}%)")
        stats_block = "\n".join(stats_lines)
        
        # Format validated pathway examples (for pattern extraction, not copying)
        success_lines = []
        for e in validated[:8]:
            pval_str = f"{e['p_value']:.2e}" if e['p_value'] else "N/A"
            success_lines.append(
                f"  - [{e['pathway_source']}] \"{e['pathway_name']}\" "
                f"(disease: {e['disease_name']}, p={pval_str})"
            )
        
        failure_lines = []
        for e in failed[:5]:
            failure_lines.append(
                f"  - [{e['pathway_source']}] \"{e['pathway_name']}\" "
                f"(disease: {e['disease_name']})"
            )
        
        success_block = "\n".join(success_lines) if success_lines else "  (none available)"
        failure_block = "\n".join(failure_lines) if failure_lines else "  (none available)"
        
        # Meta-guidance extraction prompt (v2)
        system_prompt = (
            "You are a biomedical pathway analysis advisor. "
            "Your task is to analyze cross-disease pathway validation results and extract "
            "ACTIONABLE prediction guidelines — not specific pathway names, but patterns "
            "about what TYPES of predictions tend to validate vs fail."
        )
        
        user_prompt = f"""Analyze the following cross-disease pathway validation results and extract prediction guidelines.

Validation statistics by category:
{stats_block}

Examples of VALIDATED pathways (p < 0.05):
{success_block}

Examples of FAILED pathways:
{failure_block}

Target disease: {disease_name}
Disease context: {disease_description[:300]}

Extract 3-4 concise, actionable guidelines about HOW to predict better pathways.
Focus on:
1. What LEVEL OF SPECIFICITY works best? (e.g., child vs parent GO terms, specific vs broad pathways)
2. What BIOLOGICAL THEMES recur in validated pathways for this disease context?
3. What COMMON MISTAKES lead to failed predictions? (e.g., too generic, wrong subcellular context)
4. What DATABASE-SPECIFIC patterns matter? (e.g., KEGG naming conventions, Reactome hierarchy levels)

Do NOT list specific pathway names to copy. Extract the underlying prediction PRINCIPLES.

Output format (keep each to 1-2 sentences):
GUIDELINE 1: [guideline]
GUIDELINE 2: [guideline]
GUIDELINE 3: [guideline]
GUIDELINE 4: [guideline]"""

        try:
            client = self._get_openai_client()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_completion_tokens=600
            )
            from api_cost_tracker import cost_tracker as _ct
            _ct.track(response)
            strategy_text = response.choices[0].message.content.strip()
            print(f"      🧠 Meta-guidance extraction complete ({len(strategy_text)} chars)")
            return strategy_text
        except Exception as e:
            print(f"      ⚠️  Meta-guidance extraction failed: {e}")
            return ""
    
    def format_strategy_context_for_generation(
        self,
        strategy_text: str
    ) -> str:
        """
        Format extracted meta-guidance for injection into USER PROMPT.
        
        Key change from v1: output is designed for user prompt injection
        (not system prompt), to maximize LLM attention.
        
        Parameters
        ----------
        strategy_text : str
            Output from extract_strategy_from_experiences()
            
        Returns
        -------
        Formatted string for injection into generation USER prompt
        """
        if not strategy_text:
            return ""
        
        lines = [
            "",
            "## Lessons from Similar Disease Analyses",
            "When analyzing similar disease modules, the following prediction patterns were observed:",
            "",
            strategy_text,
            "",
            "Use these patterns to guide your biological reasoning, but generate pathways "
            "based on your own analysis of the gene module above."
        ]
        
        return "\n".join(lines)
    
    def format_rag_context_for_ranking(
        self,
        pathway_names: List[str],
        current_disease_id: Optional[str] = None,
        exclude_module_id: Optional[int] = None
    ) -> str:
        """
        Format per-pathway historical evidence for the ranking stage.
        
        For each pathway being ranked, provides cross-disease validation history.
        
        Parameters
        ----------
        pathway_names : List[str]
            Names of pathways being ranked in current batch
        current_disease_id : str, optional
            Current disease ID (excluded from history to avoid leakage)
        exclude_module_id : int, optional
            Exclude this module (for within-disease cross-module retrieval).
            When set with current_disease_id=None, enables cross-module memory
            within the same disease.
            
        Returns
        -------
        Formatted string for injection into ranking prompt
        """
        cursor = self.conn.cursor()
        
        evidence_lines = ["## Cross-Disease Pathway Evidence (from Memory Bank)"]
        has_evidence = False
        
        for pw_name in pathway_names:
            # Build exclusion conditions
            conditions = ["pathway_name = ?"]
            params = [pw_name]
            if current_disease_id:
                conditions.append("mesh_id != ?")
                params.append(current_disease_id)
            if exclude_module_id is not None:
                conditions.append("module_id != ?")
                params.append(exclude_module_id)
            
            where_clause = " AND ".join(conditions)
            cursor.execute(f"""
                SELECT disease_name, gpt_rank, p_value, success_score
                FROM pathway_experiences
                WHERE {where_clause}
                ORDER BY success_score DESC
                LIMIT 5
            """, params)
            
            rows = cursor.fetchall()
            if rows:
                has_evidence = True
                diseases_seen = len(set(r[0] for r in rows))
                validated = sum(1 for r in rows if r[2] and r[2] < 0.05)
                avg_rank = np.mean([r[1] for r in rows if r[1]]) if any(r[1] for r in rows) else None
                
                rank_str = f", avg rank={avg_rank:.0f}" if avg_rank else ""
                evidence_lines.append(
                    f"- \"{pw_name}\": seen in {diseases_seen} disease(s), "
                    f"validated {validated}/{len(rows)} times{rank_str}"
                )
        
        if not has_evidence:
            return ""  # No historical data — don't add noise
        
        evidence_lines.append("")
        evidence_lines.append("Use this cross-disease evidence as ONE factor in your ranking assessment.")
        
        return "\n".join(evidence_lines)
    
    def get_embedding_stats(self) -> Dict[str, Any]:
        """Get statistics about stored embeddings."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM pathway_embeddings")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM pathway_experiences")
        total_exp = cursor.fetchone()[0]
        cursor.execute("SELECT DISTINCT model_name FROM pathway_embeddings")
        models = [r[0] for r in cursor.fetchall()]
        return {
            'total_embeddings': total,
            'total_experiences': total_exp,
            'coverage': f"{total}/{total_exp} ({100*total/total_exp:.1f}%)" if total_exp > 0 else "0/0",
            'models': models
        }
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            print(f"  🔒 Memory Bank connection closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# Example usage
if __name__ == "__main__":
    # Demo: Create memory bank and store some test data
    print("\n" + "="*80)
    print("PATHWAY MEMORY BANK - DEMO")
    print("="*80 + "\n")
    
    with PathwayMemoryBank("test_memory_bank.db") as mb:
        # Store a test disease
        mb.store_disease_analysis(
            disease_id="D000544",
            disease_name="Alzheimer's Disease",
            description="A neurodegenerative disease characterized by...",
            num_modules=20,
            total_pathways=150,
            category="neurodegenerative"
        )
        
        # Store a test pathway experience
        mb.store_pathway_experience(
            disease_id="D000544",
            pathway_data={
                'name': "amyloid-beta metabolic process",
                'source': "GO:BP",
                'description': "The chemical reactions involving amyloid-beta...",
                'gpt_rank': 1,
                'p_value': 1.5e-8,
                'pubmed_papers': [{'pmid': '12345'}, {'pmid': '67890'}]
            },
            iteration_context={
                'module_id': 5,
                'iteration': 1,
                'disease_name': "Alzheimer's Disease",
                'total_candidates': 200
            }
        )
        
        # Get statistics
        stats = mb.get_statistics()
        print("\nMemory Bank Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        # Export summary
        mb.export_knowledge_summary("test_summary.txt")
        
    print("\n✅ Demo complete!")
