#!/bin/bash
# User management script for Chainlit
# Allows creating, updating, and deleting user accounts

set -e

cd "$(dirname "$0")/.."

CONTAINER_NAME="chat_ui_app"

# Check if app container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "ERROR: Chainlit app container (${CONTAINER_NAME}) is not running!"
  echo "Please start it first with: ./docker_files/start_all.sh"
  exit 1
fi

show_help() {
  echo "User Management for Chainlit"
  echo ""
  echo "Usage: $0 [command] [options]"
  echo ""
  echo "Commands:"
  echo "  list                    List all users"
  echo "  create <username>       Create a new user (prompts for password)"
  echo "  password <username>     Change user password (prompts for new password)"
  echo "  delete <username>       Delete a user"
  echo "  help                    Show this help message"
  echo ""
  echo "Examples:"
  echo "  $0 list"
  echo "  $0 create john.doe"
  echo "  $0 password john.doe"
  echo "  $0 delete john.doe"
  echo ""
}

list_users() {
  echo "Listing all users..."
  docker exec -i ${CONTAINER_NAME} python3 <<'PYTHON_EOF'
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os

async def list_users():
    db_url = os.getenv('DATABASE_URL', 'postgresql+asyncpg://chainlit:chainlit@127.0.0.1:5432/chainlit')
    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        result = await conn.execute(text(
            'SELECT id, identifier, metadata, "createdAt" '
            'FROM users '
            'ORDER BY "createdAt" DESC'
        ))

        users = result.fetchall()

        if not users:
            print('No users found.')
        else:
            print(f'Total users: {len(users)}')
            print('')
            header = f"{'ID':<38} {'Username':<30} {'Created':<30}"
            print(header)
            print('-' * 100)
            for user in users:
                user_id = str(user[0])[:36]
                username = str(user[1])[:29]
                created = str(user[3])[:29] if user[3] else 'N/A'
                print(f"{user_id:<38} {username:<30} {created:<30}")

    await engine.dispose()

asyncio.run(list_users())
PYTHON_EOF
}

create_user() {
  local username="$1"

  if [ -z "$username" ]; then
    echo "ERROR: Username is required"
    echo "Usage: $0 create <username>"
    exit 1
  fi

  echo "Creating user: $username"
  read -s -p "Enter password: " password
  echo ""
  read -s -p "Confirm password: " password_confirm
  echo ""

  if [ "$password" != "$password_confirm" ]; then
    echo "ERROR: Passwords do not match!"
    exit 1
  fi

  docker exec -i ${CONTAINER_NAME} python3 <<PYTHON_EOF
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os
import hashlib
import secrets
from datetime import datetime
import json

async def create_user(username, password):
    db_url = os.getenv('DATABASE_URL', 'postgresql+asyncpg://chainlit:chainlit@127.0.0.1:5432/chainlit')
    engine = create_async_engine(db_url)

    import bcrypt
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    created_at = datetime.utcnow().isoformat() + 'Z'

    async with engine.begin() as conn:
        # Check if user exists
        result = await conn.execute(
            text('SELECT id FROM users WHERE identifier = :username'),
            {'username': username}
        )

        if result.fetchone():
            print(f'ERROR: User {username} already exists!')
            await engine.dispose()
            return

        # Create user with UUID
        import uuid
        user_id = str(uuid.uuid4())

        # Prepare metadata as JSON string
        metadata = {'password_hash': password_hash, 'provider': 'credentials'}
        metadata_json = json.dumps(metadata)

        await conn.execute(
            text(
                'INSERT INTO users (id, identifier, metadata, "createdAt") '
                'VALUES (:user_id, :username, CAST(:metadata AS jsonb), :created_at)'
            ),
            {
                'user_id': user_id,
                'username': username,
                'metadata': metadata_json,
                'created_at': created_at
            }
        )

        print(f'User {username} created successfully!')
        print(f'User ID: {user_id}')

    await engine.dispose()

asyncio.run(create_user('$username', '$password'))
PYTHON_EOF
}

change_password() {
  local username="$1"

  if [ -z "$username" ]; then
    echo "ERROR: Username is required"
    echo "Usage: $0 password <username>"
    exit 1
  fi

  echo "Changing password for user: $username"
  read -s -p "Enter new password: " password
  echo ""
  read -s -p "Confirm new password: " password_confirm
  echo ""

  if [ "$password" != "$password_confirm" ]; then
    echo "ERROR: Passwords do not match!"
    exit 1
  fi

  docker exec -i ${CONTAINER_NAME} python3 <<PYTHON_EOF
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os
import hashlib
import secrets
import json

async def change_password(username, password):
    db_url = os.getenv('DATABASE_URL', 'postgresql+asyncpg://chainlit:chainlit@127.0.0.1:5432/chainlit')
    engine = create_async_engine(db_url)

    import bcrypt
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    async with engine.begin() as conn:
        # Check if user exists
        result = await conn.execute(
            text('SELECT id, metadata FROM users WHERE identifier = :username'),
            {'username': username}
        )

        user = result.fetchone()
        if not user:
            print(f'ERROR: User {username} not found!')
            await engine.dispose()
            return

        # Update metadata with new password
        metadata = user[1] if user[1] else {}
        metadata['password_hash'] = password_hash
        metadata.pop('salt', None)  # Remove legacy salt

        # Convert to JSON string
        metadata_json = json.dumps(metadata)

        await conn.execute(
            text('UPDATE users SET metadata = CAST(:metadata AS jsonb) WHERE identifier = :username'),
            {'username': username, 'metadata': metadata_json}
        )

        print(f'Password for {username} updated successfully!')

    await engine.dispose()

asyncio.run(change_password('$username', '$password'))
PYTHON_EOF
}

delete_user() {
  local username="$1"

  if [ -z "$username" ]; then
    echo "ERROR: Username is required"
    echo "Usage: $0 delete <username>"
    exit 1
  fi

  read -p "Are you sure you want to delete user '$username'? (yes/no): " confirm

  if [ "$confirm" != "yes" ]; then
    echo "Deletion cancelled."
    exit 0
  fi

  docker exec -i ${CONTAINER_NAME} python3 <<PYTHON_EOF
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os

async def delete_user(username):
    db_url = os.getenv('DATABASE_URL', 'postgresql+asyncpg://chainlit:chainlit@127.0.0.1:5432/chainlit')
    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        # Check if user exists
        result = await conn.execute(
            text('SELECT id FROM users WHERE identifier = :username'),
            {'username': username}
        )

        if not result.fetchone():
            print(f'ERROR: User {username} not found!')
            await engine.dispose()
            return

        # Delete user
        await conn.execute(
            text('DELETE FROM users WHERE identifier = :username'),
            {'username': username}
        )

        print(f'User {username} deleted successfully!')

    await engine.dispose()

asyncio.run(delete_user('$username'))
PYTHON_EOF
}

# Main command handler
case "$1" in
  list)
    list_users
    ;;
  create)
    create_user "$2"
    ;;
  password)
    change_password "$2"
    ;;
  delete)
    delete_user "$2"
    ;;
  help|--help|-h|"")
    show_help
    ;;
  *)
    echo "ERROR: Unknown command: $1"
    echo ""
    show_help
    exit 1
    ;;
esac
