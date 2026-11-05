"""RAG System - Document Processing and Context-Aware Answering"""
import os
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Any, Iterator
from dataclasses import dataclass
import PyPDF2
from docx import Document
import numpy as np

# LangChain imports for document processing
try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    LANGCHAIN_AVAILABLE = True
except ImportError:
    try:
        from langchain_community.text_splitter import RecursiveCharacterTextSplitter
        LANGCHAIN_AVAILABLE = True
    except ImportError:
        LANGCHAIN_AVAILABLE = False

from memory_system import VectorStore, Memory
from config.settings import DOCUMENTS_DIR, memory_config
from utils.logger import get_logger

logger = get_logger("rag_system")

@dataclass
class DocumentChunk:
    """Chunk of a document with metadata"""
    content: str
    source: str  # File path
    chunk_id: str
    page_num: Optional[int] = None
    section: Optional[str] = None
    metadata: Dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class ProcessedDocument:
    """Fully processed document"""
    source: str
    filename: str
    doc_type: str
    chunks: List[DocumentChunk]
    total_pages: int = 0
    metadata: Dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class DocumentLoader:
    """Load documents from various formats"""
    
    SUPPORTED_TYPES = {'.pdf', '.txt', '.md', '.docx', '.doc'}
    
    def load(self, file_path: str) -> Optional[ProcessedDocument]:
        """Load and process a document file"""
        path = Path(file_path)
        
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            return None
        
        ext = path.suffix.lower()
        
        if ext not in self.SUPPORTED_TYPES:
            logger.error(f"Unsupported file type: {ext}")
            return None
        
        try:
            if ext == '.pdf':
                return self._load_pdf(path)
            elif ext in ['.txt', '.md']:
                return self._load_text(path)
            elif ext == '.docx':
                return self._load_docx(path)
            else:
                logger.error(f"Handler not implemented for: {ext}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to load {file_path}: {e}")
            return None
    
    def _load_pdf(self, path: Path) -> ProcessedDocument:
        """Load PDF document"""
        with open(path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            total_pages = len(reader.pages)
            
            pages_text = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                pages_text.append((i + 1, text))
        
        # Combine all text
        full_text = "\n\n".join([f"--- Page {p[0]} ---\n{p[1]}" for p in pages_text])
        
        return ProcessedDocument(
            source=str(path),
            filename=path.name,
            doc_type='pdf',
            chunks=[],  # Will be populated by chunker
            total_pages=total_pages,
            metadata={"pages": total_pages}
        )
    
    def _load_text(self, path: Path) -> ProcessedDocument:
        """Load text/markdown file"""
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        return ProcessedDocument(
            source=str(path),
            filename=path.name,
            doc_type='text',
            chunks=[],
            metadata={"size": len(content)}
        )
    
    def _load_docx(self, path: Path) -> ProcessedDocument:
        """Load Word document"""
        doc = Document(path)
        
        paragraphs = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)
        
        return ProcessedDocument(
            source=str(path),
            filename=path.name,
            doc_type='docx',
            chunks=[],
            metadata={"paragraphs": len(paragraphs)}
        )
    
    def load_directory(self, directory: str, recursive: bool = True) -> List[ProcessedDocument]:
        """Load all documents from a directory"""
        docs = []
        path = Path(directory)
        
        pattern = "**/*" if recursive else "*"
        for file_path in path.glob(pattern):
            if file_path.suffix.lower() in self.SUPPORTED_TYPES:
                doc = self.load(str(file_path))
                if doc:
                    docs.append(doc)
        
        return docs

class TextChunker:
    """Split documents into semantic chunks"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        if LANGCHAIN_AVAILABLE:
            self.splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""]
            )
    
    def chunk_document(self, doc: ProcessedDocument) -> ProcessedDocument:
        """Split document into chunks"""
        # Load full text based on type
        text = self._extract_full_text(doc)
        
        if LANGCHAIN_AVAILABLE:
            chunks = self.splitter.split_text(text)
        else:
            chunks = self._simple_chunk(text)
        
        # Create chunk objects
        doc.chunks = []
        for i, chunk_text in enumerate(chunks):
            chunk_id = hashlib.md5(f"{doc.source}_{i}".encode()).hexdigest()[:12]
            
            # Try to extract page number
            page_match = re.search(r'--- Page (\d+) ---', chunk_text)
            page_num = int(page_match.group(1)) if page_match else None
            
            # Clean chunk text
            clean_text = re.sub(r'--- Page \d+ ---\n?', '', chunk_text).strip()
            
            doc.chunks.append(DocumentChunk(
                content=clean_text,
                source=doc.source,
                chunk_id=chunk_id,
                page_num=page_num,
                metadata={
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                }
            ))
        
        return doc
    
    def _extract_full_text(self, doc: ProcessedDocument) -> str:
        """Extract full text from document based on type"""
        if doc.doc_type == 'pdf':
            with open(doc.source, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                pages = []
                for i, page in enumerate(reader.pages):
                    text = page.extract_text()
                    pages.append(f"--- Page {i+1} ---\n{text}")
                return "\n\n".join(pages)
        
        elif doc.doc_type in ['text', 'docx']:
            with open(doc.source, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        
        return ""
    
    def _simple_chunk(self, text: str) -> List[str]:
        """Simple fallback chunking"""
        chunks = []
        current_chunk = []
        current_size = 0
        
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        for sentence in sentences:
            sentence_size = len(sentence)
            
            if current_size + sentence_size > self.chunk_size and current_chunk:
                chunks.append(' '.join(current_chunk))
                # Keep overlap
                overlap_size = 0
                overlap = []
                for s in reversed(current_chunk):
                    if overlap_size + len(s) < self.chunk_overlap:
                        overlap.insert(0, s)
                        overlap_size += len(s)
                    else:
                        break
                current_chunk = overlap
                current_size = overlap_size
            
            current_chunk.append(sentence)
            current_size += sentence_size
        
        if current_chunk:
            chunks.append(' '.join(current_chunk))
        
        return chunks

class RAGSystem:
    """Main RAG system combining all components"""
    
    def __init__(self):
        self.loader = DocumentLoader()
        self.chunker = TextChunker()
        self.vector_store = VectorStore()  # Reuse from memory system
        self.processed_docs: Dict[str, ProcessedDocument] = {}
    
    def ingest_document(self, file_path: str) -> bool:
        """Process and store a single document"""
        try:
            # Load
            doc = self.loader.load(file_path)
            if not doc:
                return False
            
            # Chunk
            doc = self.chunker.chunk_document(doc)
            
            # Store in vector database
            for chunk in doc.chunks:
                memory = Memory(
                    id=chunk.chunk_id,
                    content=chunk.content,
                    category="document",
                    timestamp=__import__('datetime').datetime.now(),
                    metadata={
                        "source": chunk.source,
                        "page": chunk.page_num,
                        "filename": doc.filename,
                        "chunk_metadata": chunk.metadata
                    }
                )
                self.vector_store.add_memory(memory)
            
            # Track processed document
            self.processed_docs[doc.source] = doc
            
            logger.info(f"Ingested {doc.filename} with {len(doc.chunks)} chunks")
            return True
            
        except Exception as e:
            logger.error(f"Ingestion failed for {file_path}: {e}")
            return False
    
    def ingest_directory(self, directory: str, recursive: bool = True) -> Dict:
        """Process all documents in a directory"""
        results = {
            "success": [],
            "failed": []
        }
        
        path = Path(directory)
        pattern = "**/*" if recursive else "*"
        
        for file_path in path.glob(pattern):
            if file_path.suffix.lower() in self.loader.SUPPORTED_TYPES:
                if self.ingest_document(str(file_path)):
                    results["success"].append(str(file_path))
                else:
                    results["failed"].append(str(file_path))
        
        logger.info(f"Directory ingestion: {len(results['success'])} success, "
                   f"{len(results['failed'])} failed")
        return results
    
    def query(self, question: str, top_k: int = 5) -> Dict:
        """
        Query documents and return relevant context
        """
        try:
            # Search vector store
            results = self.vector_store.search(
                question, 
                top_k=top_k, 
                category="document"
            )
            
            if not results:
                return {
                    "success": True,
                    "answer_context": "",
                    "sources": [],
                    "message": "No relevant documents found"
                }
            
            # Build context
            context_parts = []
            sources = []
            
            for memory, score in results:
                chunk_text = memory.content
                source = memory.metadata.get("source", "Unknown")
                page = memory.metadata.get("page")
                
                # Add to context
                ref = f"[Source: {Path(source).name}"
                if page:
                    ref += f", Page {page}"
                ref += "]"
                
                context_parts.append(f"{chunk_text}\n{ref}")
                
                # Track unique sources
                if source not in [s["file"] for s in sources]:
                    sources.append({
                        "file": source,
                        "filename": memory.metadata.get("filename", Path(source).name),
                        "relevance": score
                    })
            
            full_context = "\n\n".join(context_parts)
            
            return {
                "success": True,
                "answer_context": full_context,
                "sources": sources,
                "relevance_scores": [r[1] for r in results],
                "message": f"Found {len(results)} relevant passages from {len(sources)} documents"
            }
            
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Query failed: {e}"
            }
    
    def get_document_list(self) -> List[Dict]:
        """Get list of processed documents"""
        return [
            {
                "filename": doc.filename,
                "path": doc.source,
                "type": doc.doc_type,
                "chunks": len(doc.chunks),
                "metadata": doc.metadata
            }
            for doc in self.processed_docs.values()
        ]
    
    def delete_document(self, file_path: str) -> bool:
        """Remove document from index"""
        try:
            doc = self.processed_docs.get(file_path)
            if doc:
                for chunk in doc.chunks:
                    self.vector_store.delete_memory(chunk.chunk_id)
                del self.processed_docs[file_path]
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete document: {e}")
            return False

# Document upload handler
class DocumentUploadHandler:
    """Handle document uploads and processing"""
    
    def __init__(self, rag_system: RAGSystem):
        self.rag = rag_system
        self.upload_dir = DOCUMENTS_DIR
        self.upload_dir.mkdir(parents=True, exist_ok=True)
    
    def save_upload(self, file_data: bytes, filename: str) -> str:
        """Save uploaded file and process"""
        # Generate unique filename
        timestamp = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w\-_.]', '_', filename)
        unique_name = f"{timestamp}_{safe_name}"
        
        file_path = self.upload_dir / unique_name
        
        # Save
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        # Process
        if self.rag.ingest_document(str(file_path)):
            return str(file_path)
        else:
            # Cleanup on failure
            file_path.unlink(missing_ok=True)
            return None
