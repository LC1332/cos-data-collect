"""Bangumi API 客户端封装。

基于 https://bangumi.github.io/api/ (v0) 文档实现。
"""

import os
import time
import logging
from typing import Any, Dict, List, Optional, Union

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bgm.tv"
REQUEST_INTERVAL = 0.35  # 请求间隔(秒)，避免触发频率限制


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

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _get(self, path: str, params: Optional[dict] = None) -> Union[dict, list]:
        self._throttle()
        url = f"{BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_body: dict, params: Optional[dict] = None) -> dict:
        self._throttle()
        url = f"{BASE_URL}{path}"
        resp = self.session.post(url, json=json_body, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

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
