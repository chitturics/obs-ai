#!/usr/bin/env python3
"""
Delete a ChromaDB collection by name.

Usage:
    python scripts/delete_collection.py <collection_name>
    python scripts/delete_collection.py --list                    # List all collections
    python scripts/delete_collection.py <collection_name> --force # Skip confirmation
    python scripts/delete_collection.py --all --force             # Delete ALL collections

Environment Variables:
    CHROMA_HTTP_URL: ChromaDB server URL (default: http://127.0.0.1:8001)
"""

import argparse
import os
import sys

# ChromaDB v2 API uses chromadb.HttpClient
try:
    import chromadb
except ImportError:
    print("ERROR: chromadb package not installed. Run: pip install chromadb")
    sys.exit(1)


def get_chroma_client():
    """Connect to ChromaDB using HTTP client (v2 API)."""
    chroma_url = os.getenv("CHROMA_HTTP_URL", "http://127.0.0.1:8001")

    # Parse URL to extract host and port
    url = chroma_url.replace("http://", "").replace("https://", "")
    if ":" in url:
        host, port_str = url.split(":", 1)
        port = int(port_str.split("/")[0])  # Handle trailing path
    else:
        host = url.split("/")[0]
        port = 8001

    try:
        client = chromadb.HttpClient(host=host, port=port)
        # Test connection with heartbeat
        client.heartbeat()
        return client
    except Exception as e:
        print(f"ERROR: Cannot connect to ChromaDB at {chroma_url}")
        print(f"  Details: {e}")
        print("\nMake sure ChromaDB is running:")
        print("  podman start chat_chroma_db")
        print("  # or: bash docker_files/start_all.sh")
        sys.exit(1)


def list_collections(client):
    """List all collections with their document counts."""
    try:
        collections = client.list_collections()

        if not collections:
            print("No collections found in ChromaDB.")
            return []

        print(f"\nFound {len(collections)} collection(s):\n")
        print(f"{'Collection Name':<45} {'Documents':>10}")
        print("-" * 57)

        collection_names = []
        for c in collections:
            # Handle both old and new chromadb API
            name = c if isinstance(c, str) else c.name
            collection_names.append(name)

            try:
                coll = client.get_collection(name)
                count = coll.count()
            except Exception:
                count = "?"

            print(f"{name:<45} {count:>10}")

        print()
        return collection_names

    except Exception as e:
        print(f"ERROR: Failed to list collections: {e}")
        return []


def delete_collection(client, name: str, force: bool = False) -> bool:
    """Delete a single collection by name."""
    try:
        # Check if collection exists
        try:
            coll = client.get_collection(name)
            count = coll.count()
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                print(f"Collection '{name}' does not exist.")
                return False
            raise

        # Confirm deletion unless --force
        if not force:
            print(f"\nCollection: {name}")
            print(f"Documents:  {count}")
            print()
            response = input(f"Are you sure you want to delete '{name}'? (yes/no): ")
            if response.lower() != "yes":
                print("Cancelled.")
                return False

        # Delete the collection
        client.delete_collection(name)
        print(f"✓ Deleted collection: {name} ({count} documents)")
        return True

    except Exception as e:
        print(f"ERROR: Failed to delete '{name}': {e}")
        return False


def delete_all_collections(client, force: bool = False) -> int:
    """Delete all collections."""
    collections = client.list_collections()

    if not collections:
        print("No collections to delete.")
        return 0

    # Get names
    names = [c if isinstance(c, str) else c.name for c in collections]

    if not force:
        print(f"\nThis will delete ALL {len(names)} collections:")
        for name in names:
            print(f"  - {name}")
        print()
        response = input("Are you sure? This cannot be undone! (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled.")
            return 0

    deleted = 0
    for name in names:
        try:
            client.delete_collection(name)
            print(f"✓ Deleted: {name}")
            deleted += 1
        except Exception as e:
            print(f"✗ Failed to delete '{name}': {e}")

    print(f"\nDeleted {deleted}/{len(names)} collections.")
    return deleted


def main():
    parser = argparse.ArgumentParser(
        description="Delete ChromaDB collections by name",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/delete_collection.py --list
  python scripts/delete_collection.py feedback_qa
  python scripts/delete_collection.py negative_feedback_mxbai_embed_large --force
  python scripts/delete_collection.py --all --force
        """
    )
    parser.add_argument("collection", nargs="?", help="Collection name to delete")
    parser.add_argument("--list", "-l", action="store_true", help="List all collections")
    parser.add_argument("--all", "-a", action="store_true", help="Delete ALL collections")
    parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()

    # Must specify an action
    if not args.list and not args.all and not args.collection:
        parser.print_help()
        sys.exit(1)

    # Connect to ChromaDB
    client = get_chroma_client()
    print(f"Connected to ChromaDB at {os.getenv('CHROMA_HTTP_URL', 'http://127.0.0.1:8001')}")

    # List collections
    if args.list:
        list_collections(client)
        sys.exit(0)

    # Delete all
    if args.all:
        deleted = delete_all_collections(client, force=args.force)
        sys.exit(0 if deleted > 0 else 1)

    # Delete single collection
    if args.collection:
        success = delete_collection(client, args.collection, force=args.force)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
