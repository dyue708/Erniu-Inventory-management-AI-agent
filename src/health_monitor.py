"""
健康检查和监控模块
"""
import asyncio
import time
import json
from typing import Dict, Any, List, Optional, Callable

# 尝试导入psutil，如果失败则使用替代方案
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    import os
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path
import logging
from aiohttp import web, ClientSession
from exceptions import BaseInventoryError, exception_handler
from message_queue import MessageQueue

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """健康状态数据结构"""
    component: str
    status: str  # healthy, warning, error
    message: str = ""
    details: Dict[str, Any] = None
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()
        if self.details is None:
            self.details = {}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HealthChecker:
    """健康检查器"""

    def __init__(self):
        self.checks: Dict[str, Callable] = {}
        self.check_results: Dict[str, HealthStatus] = {}
        self.check_interval = 30  # 30秒检查一次

    def register_check(self, name: str, check_func: Callable):
        """注册健康检查函数"""
        self.checks[name] = check_func
        logger.info(f"Registered health check: {name}")

    async def run_check(self, name: str) -> HealthStatus:
        """运行单个健康检查"""
        if name not in self.checks:
            return HealthStatus(
                component=name,
                status="error",
                message=f"Health check '{name}' not found"
            )

        try:
            check_func = self.checks[name]
            if asyncio.iscoroutinefunction(check_func):
                result = await check_func()
            else:
                result = check_func()

            if isinstance(result, HealthStatus):
                return result
            elif isinstance(result, dict):
                return HealthStatus(component=name, **result)
            else:
                return HealthStatus(
                    component=name,
                    status="healthy",
                    message=str(result) if result else "OK"
                )

        except Exception as e:
            logger.error(f"Health check '{name}' failed: {e}")
            return HealthStatus(
                component=name,
                status="error",
                message=f"Check failed: {str(e)}"
            )

    async def run_all_checks(self) -> Dict[str, HealthStatus]:
        """运行所有健康检查"""
        results = {}

        for name in self.checks:
            result = await self.run_check(name)
            results[name] = result
            self.check_results[name] = result

        return results

    async def get_overall_status(self) -> Dict[str, Any]:
        """获取整体健康状态"""
        results = await self.run_all_checks()

        # 计算整体状态
        has_error = any(r.status == "error" for r in results.values())
        has_warning = any(r.status == "warning" for r in results.values())

        if has_error:
            overall_status = "error"
        elif has_warning:
            overall_status = "warning"
        else:
            overall_status = "healthy"

        return {
            "overall_status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "checks": {name: result.to_dict() for name, result in results.items()}
        }


class SystemMonitor:
    """系统资源监控"""

    def __init__(self):
        if PSUTIL_AVAILABLE:
            self.process = psutil.Process()
        else:
            self.process = None
        self.start_time = time.time()

    def get_system_stats(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        try:
            if not PSUTIL_AVAILABLE:
                return {
                    "cpu": {"system_percent": 0, "process_percent": 0},
                    "memory": {
                        "system_total": 0,
                        "system_available": 0,
                        "system_percent": 0,
                        "process_rss": 0,
                        "process_vms": 0
                    },
                    "disk": {"total": 0, "used": 0, "free": 0, "percent": 0},
                    "network": {
                        "bytes_sent": 0,
                        "bytes_recv": 0,
                        "packets_sent": 0,
                        "packets_recv": 0
                    },
                    "uptime": time.time() - self.start_time,
                    "threads": 1,
                    "note": "psutil not available - using mock data"
                }

            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)

            # 内存使用情况
            memory = psutil.virtual_memory()
            process_memory = self.process.memory_info()

            # 磁盘使用情况
            disk = psutil.disk_usage('/')

            # 网络统计
            network = psutil.net_io_counters()

            return {
                "cpu": {
                    "system_percent": cpu_percent,
                    "process_percent": self.process.cpu_percent()
                },
                "memory": {
                    "system_total": memory.total,
                    "system_available": memory.available,
                    "system_percent": memory.percent,
                    "process_rss": process_memory.rss,
                    "process_vms": process_memory.vms
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent
                },
                "network": {
                    "bytes_sent": network.bytes_sent,
                    "bytes_recv": network.bytes_recv,
                    "packets_sent": network.packets_sent,
                    "packets_recv": network.packets_recv
                },
                "uptime": time.time() - self.start_time,
                "threads": self.process.num_threads()
            }

        except Exception as e:
            logger.error(f"Failed to get system stats: {e}")
            return {"error": str(e)}

    def check_system_health(self) -> HealthStatus:
        """检查系统健康状态"""
        try:
            stats = self.get_system_stats()

            if "error" in stats:
                return HealthStatus(
                    component="system",
                    status="error",
                    message=stats["error"]
                )

            issues = []
            status = "healthy"

            # 检查CPU使用率
            if stats["cpu"]["system_percent"] > 90:
                issues.append(f"High CPU usage: {stats['cpu']['system_percent']:.1f}%")
                status = "warning"

            # 检查内存使用率
            if stats["memory"]["system_percent"] > 90:
                issues.append(f"High memory usage: {stats['memory']['system_percent']:.1f}%")
                status = "warning"

            # 检查磁盘使用率
            if stats["disk"]["percent"] > 90:
                issues.append(f"High disk usage: {stats['disk']['percent']:.1f}%")
                status = "warning"

            message = "; ".join(issues) if issues else "System resources normal"

            return HealthStatus(
                component="system",
                status=status,
                message=message,
                details=stats
            )

        except Exception as e:
            return HealthStatus(
                component="system",
                status="error",
                message=f"System check failed: {str(e)}"
            )


class HealthMonitor:
    """健康监控主类"""

    def __init__(
        self,
        message_queue: Optional[MessageQueue] = None,
        check_interval: int = 30,
        port: int = 8080
    ):
        self.message_queue = message_queue
        self.check_interval = check_interval
        self.port = port

        self.health_checker = HealthChecker()
        self.system_monitor = SystemMonitor()

        # 注册默认健康检查
        self._register_default_checks()

        # 监控历史记录
        self.history: List[Dict[str, Any]] = []
        self.max_history = 100

    def _register_default_checks(self):
        """注册默认的健康检查"""
        self.health_checker.register_check("system", self.system_monitor.check_system_health)

        if self.message_queue:
            self.health_checker.register_check("message_queue", self._check_message_queue)

    async def _check_message_queue(self) -> HealthStatus:
        """检查消息队列健康状态"""
        try:
            queue_health = await self.message_queue.health_check()

            return HealthStatus(
                component="message_queue",
                status=queue_health["status"],
                message="; ".join(queue_health["issues"]) if queue_health["issues"] else "Queue healthy",
                details=queue_health["stats"]
            )
        except Exception as e:
            return HealthStatus(
                component="message_queue",
                status="error",
                message=f"Queue check failed: {str(e)}"
            )

    async def start_monitoring(self):
        """启动监控循环"""
        logger.info("Starting health monitoring")

        while True:
            try:
                # 运行健康检查
                overall_status = await self.health_checker.get_overall_status()

                # 记录历史
                self.history.append(overall_status)
                if len(self.history) > self.max_history:
                    self.history.pop(0)

                # 记录严重问题
                if overall_status["overall_status"] == "error":
                    logger.error(f"Health check failed: {overall_status}")
                elif overall_status["overall_status"] == "warning":
                    logger.warning(f"Health check warning: {overall_status}")

                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                logger.info("Health monitoring stopped")
                break
            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(self.check_interval)

    async def get_health_report(self) -> Dict[str, Any]:
        """获取健康报告"""
        current_status = await self.health_checker.get_overall_status()
        system_stats = self.system_monitor.get_system_stats()

        report = {
            "current_status": current_status,
            "system_stats": system_stats,
            "monitoring": {
                "check_interval": self.check_interval,
                "history_count": len(self.history),
                "uptime": system_stats.get("uptime", 0)
            }
        }

        # 添加消息队列统计
        if self.message_queue:
            try:
                queue_stats = await self.message_queue.get_queue_stats()
                report["queue_stats"] = queue_stats
            except Exception as e:
                report["queue_stats_error"] = str(e)

        return report

    # Web接口
    async def health_endpoint(self, request):
        """健康检查HTTP端点"""
        try:
            status = await self.health_checker.get_overall_status()
            http_status = 200 if status["overall_status"] == "healthy" else 503

            return web.json_response(status, status=http_status)
        except Exception as e:
            return web.json_response({
                "overall_status": "error",
                "error": str(e)
            }, status=500)

    async def metrics_endpoint(self, request):
        """系统指标HTTP端点"""
        try:
            report = await self.get_health_report()
            return web.json_response(report)
        except Exception as e:
            return web.json_response({
                "error": str(e)
            }, status=500)

    async def history_endpoint(self, request):
        """健康检查历史HTTP端点"""
        try:
            limit = int(request.query.get('limit', 20))
            history = self.history[-limit:] if limit > 0 else self.history

            return web.json_response({
                "history": history,
                "count": len(history)
            })
        except Exception as e:
            return web.json_response({
                "error": str(e)
            }, status=500)

    async def start_web_server(self):
        """启动健康检查Web服务器"""
        app = web.Application()

        # 添加路由
        app.router.add_get('/health', self.health_endpoint)
        app.router.add_get('/metrics', self.metrics_endpoint)
        app.router.add_get('/history', self.history_endpoint)

        # 添加根路径
        async def root_handler(request):
            return web.json_response({
                "service": "Inventory Management Health Monitor",
                "endpoints": ["/health", "/metrics", "/history"],
                "timestamp": datetime.now().isoformat()
            })

        app.router.add_get('/', root_handler)

        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()

        logger.info(f"Health monitor web server started on port {self.port}")
        return runner

    async def cleanup_old_history(self, max_age_hours: int = 24):
        """清理旧的历史记录"""
        try:
            cutoff_time = time.time() - (max_age_hours * 3600)

            # 过滤掉过旧的记录
            self.history = [
                record for record in self.history
                if datetime.fromisoformat(record["timestamp"]).timestamp() > cutoff_time
            ]

            logger.debug(f"Cleaned up old health history, {len(self.history)} records remaining")

        except Exception as e:
            logger.error(f"Failed to cleanup old history: {e}")


# 全局健康监控实例
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor(
    message_queue: Optional[MessageQueue] = None,
    check_interval: int = 30,
    port: int = 8080
) -> HealthMonitor:
    """获取全局健康监控实例"""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor(message_queue, check_interval, port)
    return _health_monitor