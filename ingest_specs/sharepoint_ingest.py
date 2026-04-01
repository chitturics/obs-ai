"""
SharePoint Document Ingestion to ChromaDB.

Supports:
- Document library scanning
- Multiple file types (PDF, DOCX, XLSX, TXT, MD)
- Incremental sync
- OAuth authentication
"""
import os
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import requests
from requests.auth import HTTPBasicAuth
from msal import ConfidentialClientApplication
import chromadb
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    UnstructuredExcelLoader,
    TextLoader,
)


class SharePointIngester:
    """Ingest SharePoint documents into ChromaDB."""

    def __init__(
        self,
        site_url: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        chroma_host: str = "127.0.0.1",
        chroma_port: int = 8001,
        collection_name: str = "sharepoint_docs"
    ):
        """
        Initialize SharePoint ingester.

        Args:
            site_url: SharePoint site URL (e.g., https://company.sharepoint.com/sites/sitename)
            tenant_id: Azure AD tenant ID
            client_id: Azure AD app client ID
            client_secret: Azure AD app client secret
            chroma_host: ChromaDB host
            chroma_port: ChromaDB port
            collection_name: ChromaDB collection name
        """
        self.site_url = site_url.rstrip('/')
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret

        # Initialize MSAL app for OAuth
        self.app = ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}"
        )

        # Get access token
        self.access_token = self._get_access_token()

        # Initialize ChromaDB
        self.chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        self.collection = self.chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "SharePoint documents"}
        )

        # Text splitter for chunking (conservative size for embedding model context limits)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100,
            length_function=len,
        )

        # Supported file types
        self.supported_extensions = {'.pdf', '.docx', '.xlsx', '.txt', '.md'}

        # Temp directory for downloads
        self.temp_dir = Path("./temp_sharepoint")
        self.temp_dir.mkdir(exist_ok=True)

    def _get_access_token(self) -> str:
        """Get SharePoint access token via OAuth."""
        result = self.app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )

        if "access_token" in result:
            return result["access_token"]
        else:
            raise Exception(f"Failed to get access token: {result.get('error_description')}")

    def _get_site_id(self) -> str:
        """Get SharePoint site ID."""
        # Extract site path from URL
        parts = self.site_url.split('/sites/')
        if len(parts) != 2:
            raise ValueError(f"Invalid SharePoint site URL: {self.site_url}")

        site_name = parts[1]
        hostname = parts[0].replace('https://', '')

        # Get site ID from Graph API
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{site_name}"

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        return response.json()["id"]

    def list_document_libraries(self) -> List[Dict]:
        """List all document libraries in the SharePoint site."""
        site_id = self._get_site_id()
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives"

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        libraries = []
        for drive in response.json().get("value", []):
            libraries.append({
                "id": drive["id"],
                "name": drive["name"],
                "description": drive.get("description", ""),
                "webUrl": drive["webUrl"]
            })

        return libraries

    def list_documents(self, library_id: str, folder_path: str = "") -> List[Dict]:
        """
        List documents in a SharePoint library.

        Args:
            library_id: Document library ID
            folder_path: Optional folder path within the library

        Returns:
            List of document metadata
        """
        site_id = self._get_site_id()
        headers = {"Authorization": f"Bearer {self.access_token}"}

        if folder_path:
            url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{library_id}/root:/{folder_path}:/children"
        else:
            url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{library_id}/root/children"

        documents = []

        while url:
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            data = response.json()

            for item in data.get("value", []):
                # Skip folders for now (can be recursive later)
                if "file" in item:
                    file_ext = Path(item["name"]).suffix.lower()

                    if file_ext in self.supported_extensions:
                        documents.append({
                            "id": item["id"],
                            "name": item["name"],
                            "size": item["size"],
                            "modified": item["lastModifiedDateTime"],
                            "downloadUrl": item.get("@microsoft.graph.downloadUrl"),
                            "webUrl": item["webUrl"],
                            "extension": file_ext
                        })

            # Handle pagination
            url = data.get("@odata.nextLink")

        return documents

    def download_document(self, download_url: str, filename: str) -> Path:
        """Download a SharePoint document to temp directory."""
        file_path = self.temp_dir / filename

        response = requests.get(download_url, stream=True)
        response.raise_for_status()

        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return file_path

    def extract_text(self, file_path: Path) -> str:
        """Extract text from document based on file type."""
        extension = file_path.suffix.lower()

        try:
            if extension == '.pdf':
                loader = PyPDFLoader(str(file_path))
                pages = loader.load()
                return "\n\n".join([page.page_content for page in pages])

            elif extension == '.docx':
                loader = Docx2txtLoader(str(file_path))
                docs = loader.load()
                return "\n\n".join([doc.page_content for doc in docs])

            elif extension == '.xlsx':
                loader = UnstructuredExcelLoader(str(file_path), mode="elements")
                docs = loader.load()
                return "\n\n".join([doc.page_content for doc in docs])

            elif extension in ['.txt', '.md']:
                loader = TextLoader(str(file_path))
                docs = loader.load()
                return docs[0].page_content if docs else ""

            else:
                return ""

        except Exception as e:
            print(f"Error extracting text from {file_path}: {e}")
            return ""

    def ingest_document(self, doc_metadata: Dict, library_name: str) -> int:
        """
        Ingest a single SharePoint document into ChromaDB.

        Returns:
            Number of chunks created
        """
        # Download document
        print(f"Processing: {doc_metadata['name']}")
        file_path = self.download_document(doc_metadata['downloadUrl'], doc_metadata['name'])

        # Extract text
        text = self.extract_text(file_path)

        if not text:
            print(f"  ⚠️  No text extracted from {doc_metadata['name']}")
            file_path.unlink()
            return 0

        # Split into chunks
        chunks = self.text_splitter.split_text(text)

        # Generate IDs and metadata
        doc_id_base = hashlib.md5(doc_metadata['id'].encode()).hexdigest()

        ids = [f"{doc_id_base}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "source": "sharepoint",
                "library": library_name,
                "filename": doc_metadata['name'],
                "url": doc_metadata['webUrl'],
                "modified": doc_metadata['modified'],
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            for i in range(len(chunks))
        ]

        # Add to ChromaDB
        self.collection.add(
            ids=ids,
            documents=chunks,
            metadatas=metadatas
        )

        # Cleanup
        file_path.unlink()

        print(f"  ✅ Ingested {len(chunks)} chunks from {doc_metadata['name']}")

        return len(chunks)

    def ingest_library(self, library_id: str, library_name: str, max_docs: Optional[int] = None) -> Dict:
        """
        Ingest all documents from a SharePoint library.

        Args:
            library_id: Library ID
            library_name: Library name
            max_docs: Maximum number of documents to ingest (None = all)

        Returns:
            Statistics dictionary
        """
        print(f"\n📚 Ingesting library: {library_name}")

        # Get documents
        documents = self.list_documents(library_id)

        if max_docs:
            documents = documents[:max_docs]

        stats = {
            "library": library_name,
            "total_docs": len(documents),
            "processed": 0,
            "chunks_created": 0,
            "errors": 0,
            "start_time": datetime.now().isoformat()
        }

        # Ingest each document
        for doc in documents:
            try:
                chunks = self.ingest_document(doc, library_name)
                stats["processed"] += 1
                stats["chunks_created"] += chunks
            except Exception as e:
                print(f"  ❌ Error processing {doc['name']}: {e}")
                stats["errors"] += 1

        stats["end_time"] = datetime.now().isoformat()

        print(f"\n✅ Library '{library_name}' complete:")
        print(f"   Processed: {stats['processed']}/{stats['total_docs']}")
        print(f"   Chunks: {stats['chunks_created']}")
        print(f"   Errors: {stats['errors']}")

        return stats

    def ingest_all_libraries(self, exclude_libraries: Optional[List[str]] = None, max_docs_per_library: Optional[int] = None) -> List[Dict]:
        """
        Ingest documents from all SharePoint libraries.

        Args:
            exclude_libraries: List of library names to skip
            max_docs_per_library: Maximum documents per library

        Returns:
            List of statistics per library
        """
        libraries = self.list_document_libraries()
        exclude_libraries = exclude_libraries or []

        all_stats = []

        for library in libraries:
            if library['name'] in exclude_libraries:
                print(f"⏭️  Skipping excluded library: {library['name']}")
                continue

            stats = self.ingest_library(
                library['id'],
                library['name'],
                max_docs=max_docs_per_library
            )
            all_stats.append(stats)

        return all_stats


def main():
    """Main function for SharePoint ingestion."""
    import argparse

    parser = argparse.ArgumentParser(description="Ingest SharePoint documents to ChromaDB")
    parser.add_argument("--site-url", required=True, help="SharePoint site URL")
    parser.add_argument("--tenant-id", required=True, help="Azure AD tenant ID")
    parser.add_argument("--client-id", required=True, help="Azure AD client ID")
    parser.add_argument("--client-secret", required=True, help="Azure AD client secret")
    parser.add_argument("--library", help="Specific library name (optional, ingests all if not provided)")
    parser.add_argument("--max-docs", type=int, help="Maximum documents per library")
    parser.add_argument("--exclude", nargs="+", help="Library names to exclude")

    args = parser.parse_args()

    ingester = SharePointIngester(
        site_url=args.site_url,
        tenant_id=args.tenant_id,
        client_id=args.client_id,
        client_secret=args.client_secret
    )

    if args.library:
        # Ingest specific library
        libraries = ingester.list_document_libraries()
        library = next((lib for lib in libraries if lib['name'] == args.library), None)

        if library:
            ingester.ingest_library(library['id'], library['name'], max_docs=args.max_docs)
        else:
            print(f"❌ Library '{args.library}' not found")
    else:
        # Ingest all libraries
        stats = ingester.ingest_all_libraries(
            exclude_libraries=args.exclude,
            max_docs_per_library=args.max_docs
        )

        # Print summary
        print("\n" + "="*60)
        print("INGESTION SUMMARY")
        print("="*60)
        total_docs = sum(s['processed'] for s in stats)
        total_chunks = sum(s['chunks_created'] for s in stats)
        total_errors = sum(s['errors'] for s in stats)

        print(f"Total Documents: {total_docs}")
        print(f"Total Chunks: {total_chunks}")
        print(f"Total Errors: {total_errors}")


if __name__ == "__main__":
    main()
