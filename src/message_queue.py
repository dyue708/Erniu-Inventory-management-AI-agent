"""
消息队列管理器 - 基于本地文件系统
保持原有的消息存储和处理逻辑，但增加了更好的管理和监控能力
"""
import os
import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, AsyncGenerator
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from threading import Lock
from collections import deque
from exceptions import BaseInventoryError, exception_handler
from retry_manager import retry_manager, QUICK_RETRY_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class QueueMessage:
    """队列消息数据结构"""
    id: str
    content: Dict[str, Any]
    timestamp: float
    retry_count: int = 0
    status: str = "pending"  # pending, processing, completed, failed
    error_message: Optional[str] = None
    priority: int = 0  # 0=normal, 1=high, 2=urgent

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueueMessage':
        """从字典创建消息"""
        return cls(**data)

    def is_expired(self, ttl_seconds: int = 3600) -> bool:
        """检查消息是否过期"""
        return time.time() - self.timestamp > ttl_seconds


class MessageQueue:
    """消息队列管理器"""

    def __init__(
        self,
        queue_dir: str = "messages",
        max_retry_count: int = 3,
        max_queue_size: int = 1000,
        cleanup_interval: int = 300  # 5分钟清理一次
    ):
        self.queue_dir = Path(queue_dir)
        self.queue_dir.mkdir(exist_ok=True)
        self.max_retry_count = max_retry_count
        self.max_queue_size = max_queue_size
        self.cleanup_interval = cleanup_interval

        # 内存队列用于快速访问
        self._pending_queue = deque()
        self._processing_set = set()
        self._queue_lock = Lock()

        # 统计信息
        self.stats = {
            "messages_processed": 0,
            "messages_failed": 0,
            "messages_pending": 0,
            "last_cleanup": time.time()
        }

        # 启动时加载现有消息
        self._load_existing_messages()

    def _get_message_file_path(self, message_id: str) -> Path:
        """获取消息文件路径"""
        return self.queue_dir / f"{message_id}.json"

    def _load_existing_messages(self):
        """加载现有的待处理消息"""
        try:
            for file_path in self.queue_dir.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        message = QueueMessage.from_dict(data)

                        # 只加载待处理和处理中的消息
                        if message.status in ("pending", "processing"):
                            # 重置处理中的消息为待处理
                            if message.status == "processing":
                                message.status = "pending"
                                self._save_message_to_file(message)

                            with self._queue_lock:
                                self._pending_queue.append(message)

                except Exception as e:
                    logger.warning(f"Failed to load message from {file_path}: {e}")

            logger.info(f"Loaded {len(self._pending_queue)} pending messages")
            self.stats["messages_pending"] = len(self._pending_queue)

        except Exception as e:
            logger.error(f"Failed to load existing messages: {e}")

    @exception_handler(logger=logger, reraise=False)
    def _save_message_to_file(self, message: QueueMessage) -> bool:
        """保存消息到文件"""
        file_path = self._get_message_file_path(message.id)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(message.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save message {message.id}: {e}")
            return False

    @exception_handler(logger=logger, reraise=False)
    def _delete_message_file(self, message_id: str) -> bool:
        """删除消息文件"""
        file_path = self._get_message_file_path(message_id)
        try:
            if file_path.exists():
                file_path.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to delete message file {message_id}: {e}")
            return False

    async def enqueue(
        self,
        content: Dict[str, Any],
        priority: int = 0,
        message_id: Optional[str] = None
    ) -> str:
        """添加消息到队列"""
        if message_id is None:
            message_id = f"msg_{int(time.time() * 1000)}_{id(content)}"

        message = QueueMessage(
            id=message_id,
            content=content,
            timestamp=time.time(),
            priority=priority
        )

        # 检查队列大小限制
        with self._queue_lock:
            if len(self._pending_queue) >= self.max_queue_size:
                # 移除最旧的低优先级消息
                self._remove_oldest_low_priority_message()

            # 按优先级插入
            self._insert_by_priority(message)
            self.stats["messages_pending"] = len(self._pending_queue)

        # 保存到文件
        success = self._save_message_to_file(message)
        if success:
            logger.info(f"Message {message_id} enqueued with priority {priority}")
            return message_id
        else:
            # 如果保存失败，从内存队列中移除
            with self._queue_lock:
                try:
                    self._pending_queue.remove(message)
                    self.stats["messages_pending"] = len(self._pending_queue)
                except ValueError:
                    pass
            raise BaseInventoryError(f"Failed to enqueue message {message_id}")

    def _insert_by_priority(self, message: QueueMessage):
        """按优先级插入消息"""
        # 高优先级消息插入到队列前面
        if message.priority > 0:
            # 找到第一个优先级较低的位置
            for i, existing_msg in enumerate(self._pending_queue):
                if existing_msg.priority < message.priority:
                    self._pending_queue.insert(i, message)
                    return

        # 如果没有找到合适位置或者是普通优先级，添加到末尾
        self._pending_queue.append(message)

    def _remove_oldest_low_priority_message(self):
        """移除最旧的低优先级消息"""
        for i in range(len(self._pending_queue) - 1, -1, -1):
            message = self._pending_queue[i]
            if message.priority == 0:  # 普通优先级
                removed_message = self._pending_queue[i]
                del self._pending_queue[i]
                self._delete_message_file(removed_message.id)
                logger.warning(f"Removed oldest low-priority message {removed_message.id} due to queue size limit")
                break

    async def dequeue(self, timeout: Optional[float] = None) -> Optional[QueueMessage]:
        """从队列获取消息"""
        start_time = time.time()

        while True:
            with self._queue_lock:
                if self._pending_queue:
                    message = self._pending_queue.popleft()
                    message.status = "processing"
                    self._processing_set.add(message.id)
                    self.stats["messages_pending"] = len(self._pending_queue)

                    # 更新文件状态
                    self._save_message_to_file(message)
                    return message

            # 检查超时
            if timeout is not None and (time.time() - start_time) > timeout:
                return None

            # 短暂等待
            await asyncio.sleep(0.1)

    async def mark_completed(self, message_id: str, delete_file: bool = True):
        """标记消息为已完成"""
        with self._queue_lock:
            self._processing_set.discard(message_id)

        if delete_file:
            self._delete_message_file(message_id)
        else:
            # 更新状态但保留文件
            file_path = self._get_message_file_path(message_id)
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    data['status'] = 'completed'
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.error(f"Failed to update message status {message_id}: {e}")

        self.stats["messages_processed"] += 1
        logger.debug(f"Message {message_id} marked as completed")

    async def mark_failed(
        self,
        message_id: str,
        error_message: str,
        retry: bool = True
    ):
        """标记消息为失败"""
        file_path = self._get_message_file_path(message_id)

        try:
            # 读取消息
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                message = QueueMessage.from_dict(data)
            else:
                logger.error(f"Message file {message_id} not found for failure marking")
                return

            message.error_message = error_message
            message.retry_count += 1

            with self._queue_lock:
                self._processing_set.discard(message_id)

            # 决定是否重试
            if retry and message.retry_count < self.max_retry_count:
                message.status = "pending"
                # 重新加入队列，降低优先级
                message.priority = max(0, message.priority - 1)

                with self._queue_lock:
                    self._insert_by_priority(message)
                    self.stats["messages_pending"] = len(self._pending_queue)

                logger.warning(
                    f"Message {message_id} failed (attempt {message.retry_count}), "
                    f"retrying: {error_message}"
                )
            else:
                message.status = "failed"
                self.stats["messages_failed"] += 1
                logger.error(
                    f"Message {message_id} permanently failed after "
                    f"{message.retry_count} attempts: {error_message}"
                )

            # 保存更新后的消息
            self._save_message_to_file(message)

        except Exception as e:
            logger.error(f"Failed to mark message {message_id} as failed: {e}")

    async def get_queue_stats(self) -> Dict[str, Any]:
        """获取队列统计信息"""
        with self._queue_lock:
            pending_count = len(self._pending_queue)
            processing_count = len(self._processing_set)

        # 统计文件系统中的消息
        file_stats = {"completed": 0, "failed": 0, "total_files": 0}
        try:
            for file_path in self.queue_dir.glob("*.json"):
                file_stats["total_files"] += 1
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        status = data.get('status', 'unknown')
                        if status in file_stats:
                            file_stats[status] += 1
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Failed to get file stats: {e}")

        return {
            "pending": pending_count,
            "processing": processing_count,
            "completed": file_stats["completed"],
            "failed": file_stats["failed"],
            "total_files": file_stats["total_files"],
            "messages_processed": self.stats["messages_processed"],
            "messages_failed": self.stats["messages_failed"],
            "last_cleanup": datetime.fromtimestamp(self.stats["last_cleanup"]).isoformat()
        }

    async def cleanup_old_messages(self, max_age_hours: int = 24):
        """清理旧消息"""
        try:
            cutoff_time = time.time() - (max_age_hours * 3600)
            cleaned_count = 0

            for file_path in self.queue_dir.glob("*.json"):
                try:
                    # 检查文件修改时间
                    if file_path.stat().st_mtime < cutoff_time:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                        # 只删除已完成或失败的消息
                        if data.get('status') in ('completed', 'failed'):
                            file_path.unlink()
                            cleaned_count += 1

                except Exception as e:
                    logger.warning(f"Failed to cleanup message file {file_path}: {e}")

            self.stats["last_cleanup"] = time.time()
            logger.info(f"Cleaned up {cleaned_count} old message files")

        except Exception as e:
            logger.error(f"Failed to cleanup old messages: {e}")

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        stats = await self.get_queue_stats()

        # 检查队列健康状态
        health_status = "healthy"
        issues = []

        # 检查待处理消息积压
        if stats["pending"] > self.max_queue_size * 0.8:
            health_status = "warning"
            issues.append(f"High pending message count: {stats['pending']}")

        # 检查失败率
        total_processed = stats["messages_processed"] + stats["messages_failed"]
        if total_processed > 0:
            failure_rate = stats["messages_failed"] / total_processed
            if failure_rate > 0.1:  # 失败率超过10%
                health_status = "warning"
                issues.append(f"High failure rate: {failure_rate:.2%}")

        # 检查长时间处理的消息
        if stats["processing"] > 10:
            health_status = "warning"
            issues.append(f"Too many messages in processing: {stats['processing']}")

        return {
            "status": health_status,
            "issues": issues,
            "stats": stats,
            "queue_dir": str(self.queue_dir),
            "max_queue_size": self.max_queue_size
        }

    async def reset_stuck_messages(self):
        """重置卡住的消息"""
        try:
            reset_count = 0
            current_time = time.time()

            # 重置超过5分钟仍在处理的消息
            timeout_threshold = current_time - 300

            for file_path in self.queue_dir.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    if (data.get('status') == 'processing' and
                        data.get('timestamp', 0) < timeout_threshold):

                        data['status'] = 'pending'
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)

                        # 重新加入内存队列
                        message = QueueMessage.from_dict(data)
                        with self._queue_lock:
                            self._processing_set.discard(message.id)
                            self._insert_by_priority(message)
                            self.stats["messages_pending"] = len(self._pending_queue)

                        reset_count += 1

                except Exception as e:
                    logger.warning(f"Failed to reset stuck message {file_path}: {e}")

            if reset_count > 0:
                logger.info(f"Reset {reset_count} stuck messages")

        except Exception as e:
            logger.error(f"Failed to reset stuck messages: {e}")


# 全局消息队列实例
message_queue: Optional[MessageQueue] = None


def get_message_queue(queue_dir: str = "messages") -> MessageQueue:
    """获取全局消息队列实例"""
    global message_queue
    if message_queue is None:
        message_queue = MessageQueue(queue_dir)
    return message_queue