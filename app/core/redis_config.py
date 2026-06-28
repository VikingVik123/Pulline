import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from uuid import UUID
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError
from app.core.config import settings


class RedisService:
    def __init__(self):
        self.redis = None
        self._connect()

    def _connect(self):
        """Initialize Redis connection"""
        try:
            self.redis = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                encoding="utf-8",
                # ✅ Add connection pool settings
                max_connections=10,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
        except Exception as e:
            print(f"⚠️ Failed to connect to Redis: {e}")
            self.redis = None

    async def _get_redis(self):
        """Get Redis connection, reconnecting if needed"""
        if self.redis is None:
            self._connect()
        return self.redis

    async def close(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()

    async def ping(self) -> bool:
        """Test Redis connection"""
        try:
            redis_client = await self._get_redis()
            if redis_client:
                return await redis_client.ping()
            return False
        except:
            return False

    async def store_token(
        self,
        token: str,
        user_id: UUID,
        token_type: str = "access",
        expires_in: int = 900  # 15 minutes default
    ) -> None:
        """Store token in Redis with expiry"""
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return  # Silently fail if Redis is not available
            
            # Store token data
            key = f"{settings.REDIS_TOKEN_PREFIX}{token}"
            value = json.dumps({
                "user_id": str(user_id),
                "token_type": token_type,
                "created_at": datetime.utcnow().isoformat()
            })
            await redis_client.setex(key, expires_in, value)
            
            # Add to user's token list for easy revocation
            user_key = f"{settings.REDIS_USER_TOKENS_PREFIX}{user_id}"
            await redis_client.sadd(user_key, token)
            # Set expiry on the user's token set (longer than any individual token)
            await redis_client.expire(user_key, expires_in + 3600)
        except Exception as e:
            # Log but don't raise - Redis failure shouldn't break auth
            print(f"⚠️ Redis store_token error: {e}")

    async def get_token_data(self, token: str) -> Optional[Dict[str, Any]]:
        """Get token data from Redis"""
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return None
            
            key = f"{settings.REDIS_TOKEN_PREFIX}{token}"
            data = await redis_client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            print(f"⚠️ Redis get_token_data error: {e}")
            return None

    async def delete_token(self, token: str) -> bool:
        """Delete token from Redis"""
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return False
            
            # Get token data first to know user_id
            token_data = await self.get_token_data(token)
            if token_data:
                user_id = token_data.get("user_id")
                if user_id:
                    # Remove from user's token set
                    user_key = f"{settings.REDIS_USER_TOKENS_PREFIX}{user_id}"
                    await redis_client.srem(user_key, token)
            
            # Delete the token key
            key = f"{settings.REDIS_TOKEN_PREFIX}{token}"
            return await redis_client.delete(key) > 0
        except Exception as e:
            print(f"⚠️ Redis delete_token error: {e}")
            return False

    async def blacklist_token(self, token: str, expires_in: int = 900) -> None:
        """Add token to blacklist"""
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return
            
            key = f"{settings.REDIS_BLACKLIST_PREFIX}{token}"
            await redis_client.setex(
                key, 
                expires_in + settings.REDIS_TOKEN_EXPIRE_BUFFER,
                datetime.utcnow().isoformat()
            )
        except Exception as e:
            print(f"⚠️ Redis blacklist_token error: {e}")

    async def is_token_blacklisted(self, token: str) -> bool:
        """Check if token is blacklisted"""
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return False  # If Redis is down, assume token is valid
            
            key = f"{settings.REDIS_BLACKLIST_PREFIX}{token}"
            return await redis_client.exists(key) > 0
        except Exception as e:
            print(f"⚠️ Redis is_token_blacklisted error: {e}")
            return False  # On error, allow the request

    async def store_refresh_token(
        self,
        token: str,
        user_id: UUID,
        expires_in: int = 604800  # 7 days default
    ) -> None:
        """Store refresh token in Redis"""
        await self.store_token(token, user_id, "refresh", expires_in)

    async def revoke_all_user_tokens(self, user_id: UUID) -> int:
        """Revoke all tokens for a user"""
        revoked_count = 0
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return 0
            
            user_key = f"{settings.REDIS_USER_TOKENS_PREFIX}{user_id}"
            
            # Get all tokens for this user
            tokens = await redis_client.smembers(user_key)
            
            for token in tokens:
                # Blacklist each token
                await self.blacklist_token(token)
                # Delete the token data
                await self.delete_token(token)
                revoked_count += 1
            
            # Delete the user's token set
            await redis_client.delete(user_key)
            
            # Also store a user-level revocation marker for JWT validation
            # This allows checking even if token data is expired
            revocation_key = f"{settings.REDIS_BLACKLIST_PREFIX}user:{user_id}"
            await redis_client.setex(
                revocation_key,
                604800,  # 7 days
                datetime.utcnow().isoformat()
            )
            
        except Exception as e:
            print(f"⚠️ Redis revoke_all_user_tokens error: {e}")
        
        return revoked_count

    async def is_token_revoked_for_user(self, token: str, user_id: UUID) -> bool:
        """Check if token was revoked as part of user-wide revocation"""
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return False
            
            # Check if user has a revocation marker
            revocation_key = f"{settings.REDIS_BLACKLIST_PREFIX}user:{user_id}"
            revocation_time = await redis_client.get(revocation_key)
            
            if not revocation_time:
                return False
            
            # Get token creation time
            token_data = await self.get_token_data(token)
            if not token_data:
                return False
            
            token_created = token_data.get("created_at")
            if token_created:
                token_created_dt = datetime.fromisoformat(token_created)
                revocation_dt = datetime.fromisoformat(revocation_time)
                return token_created_dt < revocation_dt
            
            return False
        except Exception as e:
            print(f"⚠️ Redis is_token_revoked_for_user error: {e}")
            return False

    async def get_user_active_tokens(self, user_id: UUID) -> List[str]:
        """Get all active tokens for a user"""
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return []
            
            user_key = f"{settings.REDIS_USER_TOKENS_PREFIX}{user_id}"
            return await redis_client.smembers(user_key)
        except Exception as e:
            print(f"⚠️ Redis get_user_active_tokens error: {e}")
            return []

    async def cleanup_expired_tokens(self) -> int:
        """Clean up expired tokens (Redis handles this automatically)"""
        # Redis automatically expires keys, so this is mostly for reference
        return 0

    async def get_redis_stats(self) -> Dict[str, Any]:
        """Get Redis statistics"""
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return {"connected": False}
            
            info = await redis_client.info()
            return {
                "connected": True,
                "version": info.get("redis_version"),
                "used_memory": info.get("used_memory_human"),
                "total_connections": info.get("total_connections_received"),
                "total_commands": info.get("total_commands_processed"),
                "uptime": info.get("uptime_in_seconds")
            }
        except Exception as e:
            print(f"⚠️ Redis get_redis_stats error: {e}")
            return {"connected": False}