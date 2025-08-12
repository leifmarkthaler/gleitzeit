"""
File-based authentication storage

Handles persistent storage of users and API keys in local files.
Uses YAML for human-readable configuration and JSON for performance.
"""

import json
import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from .models import User, APIKey, Role, Permission


class AuthStorage:
    """File-based authentication storage"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize auth storage
        
        Args:
            config_dir: Directory for auth files (default: ~/.gleitzeit)
        """
        if config_dir is None:
            config_dir = Path.home() / ".gleitzeit"
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True, mode=0o700)  # Secure permissions
        
        # File paths
        self.users_file = self.config_dir / "users.yaml"
        self.api_keys_file = self.config_dir / "api_keys.json"
        self.config_file = self.config_dir / "config.yaml"
        
        # In-memory caches
        self._users: Dict[str, User] = {}
        self._api_keys: Dict[str, APIKey] = {}
        self._loaded = False
    
    def _ensure_loaded(self):
        """Ensure data is loaded from files"""
        if not self._loaded:
            self.load()
    
    def load(self):
        """Load all authentication data from files"""
        self._load_users()
        self._load_api_keys()
        self._loaded = True
    
    def save(self):
        """Save all authentication data to files"""
        self._save_users()
        self._save_api_keys()
    
    def _load_users(self):
        """Load users from YAML file"""
        if not self.users_file.exists():
            self._users = {}
            return
        
        try:
            with open(self.users_file, 'r') as f:
                users_data = yaml.safe_load(f) or {}
            
            self._users = {}
            for user_id, data in users_data.items():
                # Convert role strings back to Role enums
                roles = {Role(role_str) for role_str in data.get('roles', ['user'])}
                
                user = User(
                    user_id=user_id,
                    username=data['username'],
                    email=data.get('email'),
                    full_name=data.get('full_name'),
                    roles=roles,
                    created_at=datetime.fromisoformat(data['created_at']),
                    last_login_at=datetime.fromisoformat(data['last_login_at']) if data.get('last_login_at') else None,
                    is_active=data.get('is_active', True),
                    metadata=data.get('metadata', {})
                )
                self._users[user_id] = user
        
        except Exception as e:
            print(f"Warning: Failed to load users: {e}")
            self._users = {}
    
    def _save_users(self):
        """Save users to YAML file"""
        users_data = {}
        
        for user_id, user in self._users.items():
            users_data[user_id] = {
                'username': user.username,
                'email': user.email,
                'full_name': user.full_name,
                'roles': [role.value for role in user.roles],
                'created_at': user.created_at.isoformat(),
                'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
                'is_active': user.is_active,
                'metadata': user.metadata
            }
        
        # Write atomically
        temp_file = self.users_file.with_suffix('.tmp')
        try:
            with open(temp_file, 'w') as f:
                yaml.dump(users_data, f, default_flow_style=False, sort_keys=True)
            
            temp_file.replace(self.users_file)
            self.users_file.chmod(0o600)  # Secure permissions
        
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e
    
    def _load_api_keys(self):
        """Load API keys from JSON file"""
        if not self.api_keys_file.exists():
            self._api_keys = {}
            return
        
        try:
            with open(self.api_keys_file, 'r') as f:
                keys_data = json.load(f)
            
            self._api_keys = {}
            for key_id, data in keys_data.items():
                api_key = APIKey(
                    key_id=key_id,
                    key_hash=data['key_hash'],
                    name=data['name'],
                    user_id=data['user_id'],
                    created_at=datetime.fromisoformat(data['created_at']),
                    expires_at=datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None,
                    last_used_at=datetime.fromisoformat(data['last_used_at']) if data.get('last_used_at') else None,
                    last_used_ip=data.get('last_used_ip'),
                    is_active=data.get('is_active', True),
                    scopes=set(data.get('scopes', []))
                )
                self._api_keys[key_id] = api_key
                
                # Link to user
                if api_key.user_id in self._users:
                    self._users[api_key.user_id].api_keys[key_id] = api_key
        
        except Exception as e:
            print(f"Warning: Failed to load API keys: {e}")
            self._api_keys = {}
    
    def _save_api_keys(self):
        """Save API keys to JSON file"""
        keys_data = {}
        
        # Collect all API keys from users
        all_keys = {}
        for user in self._users.values():
            all_keys.update(user.api_keys)
        
        for key_id, api_key in all_keys.items():
            keys_data[key_id] = {
                'key_hash': api_key.key_hash,
                'name': api_key.name,
                'user_id': api_key.user_id,
                'created_at': api_key.created_at.isoformat(),
                'expires_at': api_key.expires_at.isoformat() if api_key.expires_at else None,
                'last_used_at': api_key.last_used_at.isoformat() if api_key.last_used_at else None,
                'last_used_ip': api_key.last_used_ip,
                'is_active': api_key.is_active,
                'scopes': list(api_key.scopes)
            }
        
        # Write atomically
        temp_file = self.api_keys_file.with_suffix('.tmp')
        try:
            with open(temp_file, 'w') as f:
                json.dump(keys_data, f, indent=2, sort_keys=True)
            
            temp_file.replace(self.api_keys_file)
            self.api_keys_file.chmod(0o600)  # Secure permissions
        
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e
    
    # User management
    def create_user(
        self,
        username: str,
        roles: Optional[set[Role]] = None,
        email: Optional[str] = None,
        full_name: Optional[str] = None
    ) -> User:
        """Create a new user"""
        self._ensure_loaded()
        
        # Check if username already exists
        for user in self._users.values():
            if user.username == username:
                raise ValueError(f"Username '{username}' already exists")
        
        user = User.create(
            username=username,
            roles=roles,
            email=email,
            full_name=full_name
        )
        
        self._users[user.user_id] = user
        self.save()
        return user
    
    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        self._ensure_loaded()
        return self._users.get(user_id)
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        self._ensure_loaded()
        for user in self._users.values():
            if user.username == username:
                return user
        return None
    
    def list_users(self) -> List[User]:
        """Get all users"""
        self._ensure_loaded()
        return list(self._users.values())
    
    def update_user(self, user: User):
        """Update user data"""
        self._ensure_loaded()
        if user.user_id in self._users:
            self._users[user.user_id] = user
            # Update the _api_keys index with user's keys
            for key_id, api_key in user.api_keys.items():
                self._api_keys[key_id] = api_key
            self.save()
    
    def delete_user(self, user_id: str) -> bool:
        """Delete user and all their API keys"""
        self._ensure_loaded()
        if user_id in self._users:
            # Remove user's API keys
            user = self._users[user_id]
            for key_id in list(user.api_keys.keys()):
                if key_id in self._api_keys:
                    del self._api_keys[key_id]
            
            del self._users[user_id]
            self.save()
            return True
        return False
    
    # API Key management
    def get_api_key(self, key_id: str) -> Optional[APIKey]:
        """Get API key by ID"""
        self._ensure_loaded()
        return self._api_keys.get(key_id)
    
    def authenticate_api_key(self, raw_key: str) -> Optional[APIKey]:
        """Authenticate with raw API key"""
        self._ensure_loaded()
        
        # Extract key ID from raw key (last 8 characters)
        if not raw_key.startswith('gzt_'):
            return None
            
        key_id = raw_key[-8:]
        api_key = self._api_keys.get(key_id)
        
        if api_key and api_key.matches_key(raw_key) and api_key.is_valid():
            # Update last used
            api_key.update_last_used()
            self.save()
            return api_key
        
        return None
    
    def list_api_keys(self, user_id: Optional[str] = None) -> List[APIKey]:
        """List API keys, optionally filtered by user"""
        self._ensure_loaded()
        
        keys = list(self._api_keys.values())
        if user_id:
            keys = [key for key in keys if key.user_id == user_id]
        
        return keys
    
    # Configuration management
    def get_config(self) -> Dict:
        """Get configuration settings"""
        if not self.config_file.exists():
            return {}
        
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}
    
    def save_config(self, config: Dict):
        """Save configuration settings"""
        try:
            with open(self.config_file, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
            self.config_file.chmod(0o600)
        except Exception as e:
            raise e
    
    def get_current_context(self) -> Optional[str]:
        """Get current authentication context (active API key)"""
        config = self.get_config()
        return config.get('current_context')
    
    def set_current_context(self, api_key: str):
        """Set current authentication context"""
        config = self.get_config()
        config['current_context'] = api_key
        self.save_config(config)
    
    def clear_current_context(self):
        """Clear current authentication context"""
        config = self.get_config()
        config.pop('current_context', None)
        self.save_config(config)
    
    # Utility methods
    def initialize_default_admin(self) -> tuple[User, str]:
        """Create default admin user if none exists"""
        self._ensure_loaded()
        
        # Check if any admin users exist
        admin_users = [u for u in self._users.values() if Role.ADMIN in u.roles]
        if admin_users:
            raise ValueError("Admin user already exists")
        
        # Create default admin
        admin_user = self.create_user(
            username="admin",
            roles={Role.ADMIN},
            full_name="System Administrator"
        )
        
        # Create admin API key
        api_key, raw_key = admin_user.create_api_key(
            name="Default Admin Key",
            expires_in_days=365  # 1 year expiry
        )
        
        self.save()
        return admin_user, raw_key
    
    def cleanup_expired_keys(self) -> int:
        """Remove expired API keys"""
        self._ensure_loaded()
        
        removed_count = 0
        current_time = datetime.utcnow()
        
        # Find expired keys
        expired_keys = []
        for key_id, api_key in self._api_keys.items():
            if api_key.expires_at and current_time > api_key.expires_at:
                expired_keys.append(key_id)
        
        # Remove expired keys
        for key_id in expired_keys:
            api_key = self._api_keys[key_id]
            
            # Remove from user
            if api_key.user_id in self._users:
                user = self._users[api_key.user_id]
                user.api_keys.pop(key_id, None)
            
            # Remove from global store
            del self._api_keys[key_id]
            removed_count += 1
        
        if removed_count > 0:
            self.save()
        
        return removed_count
    
    def get_stats(self) -> Dict:
        """Get storage statistics"""
        self._ensure_loaded()
        
        active_keys = sum(1 for key in self._api_keys.values() if key.is_valid())
        expired_keys = sum(1 for key in self._api_keys.values() if not key.is_valid())
        
        return {
            'total_users': len(self._users),
            'active_users': sum(1 for user in self._users.values() if user.is_active),
            'total_api_keys': len(self._api_keys),
            'active_api_keys': active_keys,
            'expired_api_keys': expired_keys,
            'config_dir': str(self.config_dir),
            'files_exist': {
                'users': self.users_file.exists(),
                'api_keys': self.api_keys_file.exists(),
                'config': self.config_file.exists()
            }
        }