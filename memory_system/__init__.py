"""Memory System - Vector Database and Conversation Storage"""
import json
import sqlite3
import pickle
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path
import faiss
from sentence_transformers import SentenceTransformer
from dataclasses import dataclass, asdict

from config.settings import memory_config, MEMORY_DIR
from utils.logger import get_logger

logger = get_logger("memory_system")

@dataclass
class Memory:
    """Single memory entry"""
    id: str
    content: str
    category: str  # "conversation", "fact", "preference", "task"
    timestamp: datetime
    metadata: Dict = None
    embedding: Optional[np.ndarray] = None
    importance: float = 1.0
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "importance": self.importance
        }

class VectorStore:
    """FAISS-based vector storage for semantic search"""
    
    def __init__(self, embedding_model: str = None):
        self.embedding_model = embedding_model or memory_config.embedding_model
        self.encoder = None
        self.index = None
        self.dimension = 384  # Default for all-MiniLM-L6-v2
        self.memories: List[Memory] = []
        self.db_path = Path(memory_config.vector_db_path)
        
        self._init_encoder()
        self._load_or_create_index()
    
    def _init_encoder(self):
        """Initialize sentence transformer"""
        try:
            self.encoder = SentenceTransformer(self.embedding_model)
            self.dimension = self.encoder.get_sentence_embedding_dimension()
            logger.info(f"Loaded embedding model: {self.embedding_model}")
        except Exception as e:
            logger.error(f"Failed to load encoder: {e}")
            raise
    
    def _load_or_create_index(self):
        """Load existing index or create new"""
        index_file = self.db_path / "faiss.index"
        memories_file = self.db_path / "memories.pkl"
        
        if index_file.exists() and memories_file.exists():
            try:
                self.index = faiss.read_index(str(index_file))
                with open(memories_file, 'rb') as f:
                    self.memories = pickle.load(f)
                logger.info(f"Loaded index with {len(self.memories)} memories")
            except Exception as e:
                logger.error(f"Failed to load index: {e}")
                self._create_new_index()
        else:
            self._create_new_index()
    
    def _create_new_index(self):
        """Create new FAISS index"""
        self.index = faiss.IndexFlatIP(self.dimension)  # Inner product for cosine similarity
        # Normalize vectors for cosine similarity
        self.index = faiss.IndexFlatIP(self.dimension)
        logger.info("Created new FAISS index")
    
    def add_memory(self, memory: Memory) -> bool:
        """Add memory to vector store"""
        try:
            # Generate embedding
            embedding = self.encoder.encode(memory.content, convert_to_numpy=True)
            embedding = embedding / np.linalg.norm(embedding)  # Normalize
            
            memory.embedding = embedding
            
            # Add to index
            self.index.add(np.array([embedding], dtype=np.float32))
            
            # Store memory
            self.memories.append(memory)
            
            # Persist
            self._save()
            
            logger.debug(f"Added memory: {memory.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add memory: {e}")
            return False
    
    def search(self, query: str, top_k: int = None, 
              category: str = None, min_score: float = None) -> List[Tuple[Memory, float]]:
        """
        Search memories by semantic similarity
        Returns list of (memory, score) tuples
        """
        if top_k is None:
            top_k = memory_config.top_k_results
        if min_score is None:
            min_score = memory_config.similarity_threshold
        
        if len(self.memories) == 0:
            return []
        
        try:
            # Generate query embedding
            query_embedding = self.encoder.encode(query, convert_to_numpy=True)
            query_embedding = query_embedding / np.linalg.norm(query_embedding)
            
            # Search
            scores, indices = self.index.search(
                np.array([query_embedding], dtype=np.float32), 
                min(top_k, len(self.memories))
            )
            
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx >= 0 and idx < len(self.memories):
                    memory = self.memories[idx]
                    
                    # Filter by category if specified
                    if category and memory.category != category:
                        continue
                    
                    # Filter by score
                    if score >= min_score:
                        results.append((memory, float(score)))
            
            return results
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def get_recent(self, category: str = None, limit: int = 10) -> List[Memory]:
        """Get recent memories"""
        filtered = self.memories
        if category:
            filtered = [m for m in filtered if m.category == category]
        
        # Sort by timestamp descending
        sorted_memories = sorted(filtered, key=lambda m: m.timestamp, reverse=True)
        return sorted_memories[:limit]
    
    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory (requires rebuilding index)"""
        try:
            self.memories = [m for m in self.memories if m.id != memory_id]
            self._rebuild_index()
            self._save()
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False
    
    def _rebuild_index(self):
        """Rebuild FAISS index from memories"""
        self._create_new_index()
        embeddings = []
        for memory in self.memories:
            if memory.embedding is not None:
                embeddings.append(memory.embedding)
        
        if embeddings:
            self.index.add(np.array(embeddings, dtype=np.float32))
    
    def _save(self):
        """Persist index and memories"""
        try:
            self.db_path.mkdir(parents=True, exist_ok=True)
            
            # Save index
            faiss.write_index(self.index, str(self.db_path / "faiss.index"))
            
            # Save memories (without embeddings to save space)
            memories_to_save = []
            for m in self.memories:
                m_copy = Memory(
                    id=m.id,
                    content=m.content,
                    category=m.category,
                    timestamp=m.timestamp,
                    metadata=m.metadata,
                    embedding=None,
                    importance=m.importance
                )
                memories_to_save.append(m_copy)
            
            with open(self.db_path / "memories.pkl", 'wb') as f:
                pickle.dump(memories_to_save, f)
                
        except Exception as e:
            logger.error(f"Failed to save index: {e}")

class ChatHistoryStore:
    """SQLite-based chat history storage"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or memory_config.chat_history_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    session_id TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    start_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    end_time TEXT,
                    summary TEXT
                )
            """)
            
            conn.commit()
    
    def add_message(self, role: str, content: str, 
                   metadata: Dict = None, session_id: str = None):
        """Add message to history"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO conversations (role, content, metadata, session_id)
                       VALUES (?, ?, ?, ?)""",
                    (role, content, json.dumps(metadata or {}), session_id)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save message: {e}")
    
    def get_history(self, session_id: str = None, limit: int = 50) -> List[Dict]:
        """Get conversation history"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                if session_id:
                    cursor = conn.execute(
                        """SELECT role, content, timestamp, metadata 
                           FROM conversations 
                           WHERE session_id = ? 
                           ORDER BY timestamp DESC LIMIT ?""",
                        (session_id, limit)
                    )
                else:
                    cursor = conn.execute(
                        """SELECT role, content, timestamp, metadata 
                           FROM conversations 
                           ORDER BY timestamp DESC LIMIT ?""",
                        (limit,)
                    )
                
                rows = cursor.fetchall()
                return [
                    {
                        "role": row[0],
                        "content": row[1],
                        "timestamp": row[2],
                        "metadata": json.loads(row[3]) if row[3] else {}
                    }
                    for row in reversed(rows)
                ]
        except Exception as e:
            logger.error(f"Failed to get history: {e}")
            return []
    
    def create_session(self, session_id: str):
        """Create new session"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (id) VALUES (?)",
                    (session_id,)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
    
    def end_session(self, session_id: str, summary: str = None):
        """End session"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """UPDATE sessions 
                       SET end_time = CURRENT_TIMESTAMP, summary = ? 
                       WHERE id = ?""",
                    (summary, session_id)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to end session: {e}")

class MemorySystem:
    """Main memory system orchestrating all components"""
    
    def __init__(self):
        self.vector_store = VectorStore()
        self.chat_history = ChatHistoryStore()
        self.current_session = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create new session
        self.chat_history.create_session(self.current_session)
    
    def add_interaction(self, user_input: str, assistant_response: str, 
                       metadata: Dict = None):
        """Store a complete interaction"""
        timestamp = datetime.now()
        
        # Store in chat history
        self.chat_history.add_message(
            "user", user_input, 
            metadata=metadata, 
            session_id=self.current_session
        )
        self.chat_history.add_message(
            "assistant", assistant_response,
            session_id=self.current_session
        )
        
        # Store as semantic memory
        combined = f"User: {user_input}\nAssistant: {assistant_response}"
        memory = Memory(
            id=f"conv_{timestamp.timestamp()}",
            content=combined,
            category="conversation",
            timestamp=timestamp,
            metadata=metadata
        )
        self.vector_store.add_memory(memory)
    
    def store_fact(self, content: str, category: str = "fact", 
                   metadata: Dict = None, importance: float = 1.0):
        """Store factual information"""
        memory = Memory(
            id=f"fact_{datetime.now().timestamp()}",
            content=content,
            category=category,
            timestamp=datetime.now(),
            metadata=metadata,
            importance=importance
        )
        return self.vector_store.add_memory(memory)
    
    def store_preference(self, key: str, value: Any, importance: float = 1.5):
        """Store user preference"""
        content = f"User preference: {key} = {value}"
        memory = Memory(
            id=f"pref_{key}",
            content=content,
            category="preference",
            timestamp=datetime.now(),
            metadata={"key": key, "value": value},
            importance=importance
        )
        return self.vector_store.add_memory(memory)
    
    def recall(self, query: str, top_k: int = 5, 
              category: str = None) -> List[Tuple[Memory, float]]:
        """Search semantic memory"""
        return self.vector_store.search(query, top_k=top_k, category=category)
    
    def get_relevant_context(self, query: str, max_tokens: int = 1000) -> str:
        """Get relevant context for query"""
        results = self.recall(query, top_k=5)
        
        if not results:
            return ""
        
        context_parts = ["Relevant information from memory:"]
        total_length = 0
        
        for memory, score in results:
            text = f"- {memory.content}"
            if total_length + len(text) > max_tokens:
                break
            context_parts.append(text)
            total_length += len(text)
        
        return "\n".join(context_parts)
    
    def get_recent_conversations(self, limit: int = 10) -> List[Dict]:
        """Get recent conversation history"""
        return self.chat_history.get_history(
            session_id=self.current_session, 
            limit=limit
        )
    
    def get_preferences(self) -> Dict:
        """Get all stored preferences"""
        prefs = self.vector_store.get_recent(category="preference", limit=50)
        result = {}
        for p in prefs:
            if "key" in p.metadata:
                result[p.metadata["key"]] = p.metadata.get("value")
        return result
    
    def close(self):
        """Close session and save"""
        self.chat_history.end_session(self.current_session)
        logger.info("Memory system closed")
