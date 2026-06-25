"""
多设备轮询调度器
=================
按配置的采集间隔轮询所有串口服务器下的从站设备，将采集到的数据交给存储模块写入数据库。
支持多串口服务器架构：每台服务器独立传输层，设备按服务器分组轮询。
"""

import asyncio
import logging
from typing import List, Optional, Callable, Awaitable
from datetime import datetime

from collector.device import Device
from transport.base import TransportBase
from config_loader import AppConfig, DeviceConfig


logger = logging.getLogger("plc_collector.collector.scheduler")


class CollectorScheduler:
    """
    多服务器多设备轮询采集调度器

    负责:
    1. 为每台服务器初始化独立的设备实例列表
    2. 按固定间隔轮询采集（遍历服务器 → 遍历其下设备）
    3. 将采集结果通过回调函数输出
    """

    def __init__(
        self,
        config: AppConfig,
        transports: List[TransportBase],
        on_data: Optional[Callable[[List[dict]], Awaitable[None]]] = None,
    ):
        """
        Args:
            config: 应用配置
            transports: 传输层实例列表，按 server_index 对应 config.servers
            on_data: 数据采集回调 (接收本轮所有设备的采集结果列表)
        """
        self._config = config
        self._transports = transports
        self._on_data = on_data
        self._devices: List[Device] = []
        self._running = False
        self._round_count = 0
        self._task: Optional[asyncio.Task] = None

        # 按服务器初始化设备列表
        for srv_idx, srv_cfg in enumerate(config.servers):
            if srv_idx >= len(transports):
                logger.warning(
                    f"服务器 {srv_cfg.name!r} (索引={srv_idx}) "
                    f"缺少对应传输层，跳过"
                )
                continue
            transport = transports[srv_idx]
            for dev_cfg in srv_cfg.devices:
                device = Device(
                    slave_addr=dev_cfg.slave_addr,
                    name=dev_cfg.name,
                    transport=transport,
                    device_type=getattr(dev_cfg, 'device_type', ''),
                    timeout=dev_cfg.timeout,
                    retry=dev_cfg.retry,
                    server_index=srv_idx,
                    server_name=srv_cfg.name,
                )
                self._devices.append(device)

        total_servers = min(len(config.servers), len(transports))
        logger.info(
            f"调度器初始化: {total_servers}台服务器, "
            f"{len(self._devices)}台设备, "
            f"采集间隔={config.scheduler.interval_seconds}s"
        )

    @property
    def devices(self) -> List[Device]:
        return self._devices

    @property
    def is_running(self) -> bool:
        return self._running

    async def _collect_one_round(self) -> List[dict]:
        """
        执行一轮完整的采集（按服务器分组轮询所有设备）

        Returns:
            本轮成功采集的数据列表
        """
        results = []

        # 按服务器分组遍历
        current_server_idx = -1
        for device in self._devices:
            if not self._running:
                break

            # 服务器切换时记录日志（可选）
            if device.server_index != current_server_idx:
                current_server_idx = device.server_index
                logger.debug(
                    f"切换到服务器: {device.server_name} "
                    f"(索引={current_server_idx})"
                )

            data = await device.collect()
            if data is not None:
                results.append(data)

            # 设备间短暂间隔，避免RS485总线拥堵
            await asyncio.sleep(0.05)

        return results

    async def _run_loop(self):
        """主采集循环"""
        interval = self._config.scheduler.interval_seconds
        logger.info(f"采集循环启动，间隔={interval}s")

        while self._running:
            round_start = asyncio.get_event_loop().time()

            try:
                results = await self._collect_one_round()
                self._round_count += 1

                if results:
                    logger.info(
                        f"[第{self._round_count}轮] "
                        f"成功采集 {len(results)}/{len(self._devices)} 台设备"
                    )
                else:
                    logger.warning(
                        f"[第{self._round_count}轮] 所有设备采集失败"
                    )

                # 回调输出数据
                if self._on_data and results:
                    try:
                        await self._on_data(results)
                    except Exception as cb_err:
                        logger.error(f"数据回调执行失败: {cb_err}")

            except Exception as e:
                logger.error(f"采集循环异常: {e}", exc_info=True)

            # 计算剩余时间 = 间隔 - 本轮采集耗时
            elapsed = asyncio.get_event_loop().time() - round_start
            remaining = max(0, interval - elapsed)

            # 拆成 1 秒小段等待，每段检查 self._running 实现快速停止
            waited = 0.0
            while self._running and waited < remaining:
                chunk = min(1.0, remaining - waited)
                try:
                    await asyncio.sleep(chunk)
                except asyncio.CancelledError:
                    break
                waited += chunk

        logger.info("采集循环已停止")

    async def start(self):
        """启动采集调度"""
        if self._running:
            logger.warning("调度器已在运行中")
            return

        # 连接所有传输层
        for idx, transport in enumerate(self._transports):
            srv_name = (
                self._config.servers[idx].name
                if idx < len(self._config.servers)
                else f"服务器{idx}"
            )
            try:
                if not transport.is_connected:
                    await transport.connect()
                logger.info(f"传输层已连接: {srv_name}")
            except Exception as e:
                logger.error(f"传输层连接失败: {srv_name} - {e}")

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("调度器已启动")

    async def stop(self):
        """停止采集调度"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # 断开所有传输层
        for idx, transport in enumerate(self._transports):
            try:
                await transport.disconnect()
            except Exception as e:
                logger.error(f"传输层断开失败 (索引={idx}): {e}")

        logger.info("调度器已停止")

    def print_stats(self):
        """打印所有设备的采集统计"""
        print("\n" + "=" * 60)
        print(f"  采集统计 (共{self._round_count}轮)")
        print("=" * 60)
        for device in self._devices:
            stats = device.stats
            print(
                f"  [{device.server_name}] "
                f"{stats['device']:12s} | "
                f"地址={stats['slave_addr']:3d} | "
                f"成功={stats['success']:5d} | "
                f"失败={stats['error']:5d} | "
                f"错误率={stats['error_rate']}"
            )
        print("=" * 60 + "\n")
