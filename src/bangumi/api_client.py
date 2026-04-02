"""Bangumi API 客户端封装。

基于 https://bangumi.github.io/api/ (v0) 文档实现。
支持自适应限流和自动重试，适合大规模数据采集。
"""

import os
import time
import logging
import random
from typing import Any, Dict, List, Optional, Union

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bgm.tv"
REQUEST_INTERVAL = 0.4
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 2


class BangumiClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("BANGUMI_API_KEY", "")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "cos-data-collect/0.1 (https://github.com/cos-data-collect)",
            "Accept": "application/json",
        })
        if self.api_key:
            self.session.headers["Authorization"] = f"Bearer {self.api_key}"
        self._last_request_time = 0.0
        self._interval = REQUEST_INTERVAL

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last_request_time = time.time()

    def _request(self, method: str, path: str, params=None, json_body=None) -> Union[dict, list]:
        url = f"{BASE_URL}{path}"
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            try:
                if method == "GET":
                    resp = self.session.get(url, params=params, timeout=30)
                else:
                    resp = self.session.post(url, json=json_body, params=params, timeout=30)

                if resp.status_code == 429:
                    wait = RETRY_BACKOFF_BASE ** attempt + random.uniform(0, 2)
                    self._interval = min(self._interval * 1.5, 5.0)
                    logger.warning(
                        f"429 Too Many Requests, 等待 {wait:.1f}s, "
                        f"间隔调整为 {self._interval:.2f}s (attempt {attempt}/{MAX_RETRIES})"
                    )
                    time.sleep(wait)
                    continue

                if resp.status_code >= 500:
                    wait = RETRY_BACKOFF_BASE ** attempt + random.uniform(0, 1)
                    logger.warning(f"HTTP {resp.status_code}, 重试 {attempt}/{MAX_RETRIES}, 等待 {wait:.1f}s")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()

                if self._interval > REQUEST_INTERVAL:
                    self._interval = max(self._interval * 0.95, REQUEST_INTERVAL)

                return resp.json()

            except requests.exceptions.Timeout:
                logger.warning(f"请求超时 {path}, 重试 {attempt}/{MAX_RETRIES}")
                time.sleep(RETRY_BACKOFF_BASE ** attempt)
            except requests.exceptions.ConnectionError:
                wait = RETRY_BACKOFF_BASE ** attempt + random.uniform(0, 2)
                logger.warning(f"连接错误 {path}, 等待 {wait:.1f}s, 重试 {attempt}/{MAX_RETRIES}")
                time.sleep(wait)

        raise requests.exceptions.RetryError(f"请求失败超过 {MAX_RETRIES} 次: {method} {path}")

    def _get(self, path: str, params: Optional[dict] = None) -> Union[dict, list]:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json_body: dict, params: Optional[dict] = None) -> dict:
        return self._request("POST", path, params=params, json_body=json_body)

    # ── 条目 (Subject) ──

    def browse_subjects(
        self, subject_type: int, sort: str = "rank",
        limit: int = 50, offset: int = 0,
    ) -> dict:
        """浏览条目列表。

        subject_type: 1=书籍, 2=动画, 3=音乐, 4=游戏, 6=三次元
        sort: 'rank' | 'date'
        """
        return self._get("/v0/subjects", params={
            "type": subject_type, "sort": sort,
            "limit": limit, "offset": offset,
        })

    def search_subjects(
        self, keyword: str = "", sort: str = "heat",
        subject_types: Optional[List[int]] = None,
        limit: int = 50, offset: int = 0,
        rank_filter: Optional[List[str]] = None,
    ) -> dict:
        """搜索条目 (POST /v0/search/subjects)。"""
        body: dict = {"keyword": keyword, "sort": sort}
        filt: dict = {}
        if subject_types:
            filt["type"] = subject_types
        if rank_filter:
            filt["rank"] = rank_filter
        if filt:
            body["filter"] = filt
        return self._post("/v0/search/subjects", body, params={
            "limit": limit, "offset": offset,
        })

    def get_subject(self, subject_id: int) -> dict:
        return self._get(f"/v0/subjects/{subject_id}")

    def get_subject_characters(self, subject_id: int) -> List[dict]:
        """获取条目的角色列表。返回 RelatedCharacter[]。"""
        return self._get(f"/v0/subjects/{subject_id}/characters")

    # ── 角色 (Character) ──

    def get_character(self, character_id: int) -> dict:
        """获取角色详情，包含 stat.collects 用于衡量人气。"""
        return self._get(f"/v0/characters/{character_id}")

    def search_characters(
        self, keyword: str, limit: int = 50, offset: int = 0,
    ) -> dict:
        """搜索角色 (POST /v0/search/characters)。需要 keyword。"""
        body = {"keyword": keyword}
        return self._post("/v0/search/characters", body, params={
            "limit": limit, "offset": offset,
        })
