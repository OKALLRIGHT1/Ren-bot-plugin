import os
import random
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont


class Plugin:
    type = "direct"
    aliases = [
        "/吃什么",
        "/今天吃什么",
        "/中午吃什么",
        "/晚上吃什么",
        "/不知道吃什么",
        "/做点什么吃",
        "/做什么吃",
        "/做点什么吃的",
        "/怎么做",
        "/做法",
    ]

    _RECIPE_REQUEST_KEYWORDS = (
        "怎么做",
        "做法",
        "咋做",
        "如何做",
        "怎么煮",
        "怎么炒",
        "怎么弄",
    )
    _COOKING_SUGGESTION_KEYWORDS = (
        "做点什么吃",
        "做什么吃",
        "做点什么吃的",
        "做啥吃",
        "做啥好",
        "做什么好",
        "煮点什么吃",
        "炒点什么吃",
    )
    _EAT_ONLY_KEYWORDS = (
        "吃什么",
        "今天吃什么",
        "中午吃什么",
        "晚上吃什么",
        "早上吃什么",
        "早餐吃什么",
        "午饭吃什么",
        "晚饭吃什么",
        "不知道吃什么",
    )
    _IGNORE_FILE_NAMES = {
        "README.md",
        "index.md",
        "development.md",
        "示例菜.md",
    }
    _IGNORE_PATH_PARTS = {
        "images",
        "docs",
        "docker_support",
        "template",
        "tips",
        "starsystem",
    }
    _NON_HOMESTYLE_CATEGORY_HINTS = {
        "配料",
        "condiment",
        "饮品",
        "drink",
    }
    _NON_HOMESTYLE_TITLE_HINTS = (
        "料",
        "酱",
        "调味",
        "汤膏",
        "糖浆",
        "特调",
        "咖啡",
        "冰沙",
        "鸡尾酒",
    )
    _LIGHT_HINTS = (
        "清",
        "蒸",
        "汤",
        "粥",
        "羹",
        "凉拌",
        "白灼",
        "豆腐",
        "青菜",
        "南瓜",
    )
    _HEAVY_HINTS = (
        "炸",
        "辣",
        "麻辣",
        "肥肠",
        "红烧",
        "扣肉",
        "卤",
        "锅",
        "烧烤",
    )
    _BREAKFAST_HINTS = (
        "早餐",
        "breakfast",
        "粥",
        "豆浆",
        "包子",
        "花卷",
        "三明治",
        "烧麦",
        "水煮蛋",
        "茶叶蛋",
    )
    _LUNCH_HINTS = (
        "主食",
        "staple",
        "盖饭",
        "炒饭",
        "面",
        "米线",
        "饭",
        "便当",
    )
    _DINNER_HINTS = (
        "晚餐",
        "家常",
        "汤",
        "炖",
        "蒸菜",
        "炒菜",
        "soup",
        "vegetable_dish",
        "meat_dish",
    )
    _IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    _MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
    _RARITY_COLORS = {
        2: (98, 152, 255),
        3: (163, 102, 255),
        4: (255, 186, 59),
        5: (255, 117, 190),
    }
    _FONT_CANDIDATES = (
        "msyh.ttc",
        "msyh.ttf",
        "msyhbd.ttc",
        "simhei.ttf",
        "simsun.ttc",
    )
    _RARITY_ORDER = (2, 3, 4, 5)
    _GACHA_PROBABILITIES = (
        (2, 0.40),
        (3, 0.35),
        (4, 0.20),
        (5, 0.05),
    )
    _CARD_FRAME_FILES = {
        2: "frame-2.png",
        3: "frame-3.png",
        4: "frame-4.png",
        5: "frame-5.png",
    }

    def __init__(self):
        self._rate_records: Dict[str, List[float]] = {}
        self._session_cooldown_until: Dict[str, float] = {}
        self._recipes_cache: List[Dict[str, Any]] | None = None
        self._recipes_mtime: float = 0.0

    def should_handle_direct(self, text: str, context: Dict, key: str) -> bool:
        raw = str(text or "").strip().lower()
        if not raw:
            return False
        if not raw.startswith("/"):
            return False
        return any(keyword in raw for keyword in self.aliases)

    async def run(self, args: str, ctx: Dict[str, Any]) -> Any:
        user_text = str(args or "").strip()
        recipes = self._load_recipes()
        if not recipes:
            return "菜谱库还没准备好。"

        draw_count = self._extract_draw_count(user_text)
        mode = self._detect_mode(user_text)
        if mode == "recipe_lookup":
            recipe = self._find_recipe_from_text(user_text, recipes)
            if not recipe:
                return "你可以这样说：`/西红柿炒鸡蛋怎么做` 或 `/做法 西红柿炒鸡蛋`"
            return self._build_recipe_reply(recipe, ctx)

        if mode == "cook_suggestion":
            recipe = self._pick_recipe(user_text, ctx, recipes, allow_cooldown=False)
            if not recipe:
                return "我一时想不到做什么，你自己决定吧。"
            return self._build_recipe_suggestion_reply(recipe, ctx)

        if draw_count > 1:
            picks = self._pick_multiple_recipes(user_text, ctx, recipes, draw_count)
            return self._build_gacha_reply(picks, ctx, draw_count)

        recipe = self._pick_recipe(user_text, ctx, recipes, allow_cooldown=True)
        if not recipe:
            return ""
        return self._build_food_reply(recipe, ctx)

    def _detect_mode(self, text: str) -> str:
        raw = str(text or "").strip().lower()
        if any(keyword in raw for keyword in self._RECIPE_REQUEST_KEYWORDS):
            return "recipe_lookup"
        if any(keyword in raw for keyword in self._COOKING_SUGGESTION_KEYWORDS):
            return "cook_suggestion"
        return "eat_only"

    def _extract_draw_count(self, text: str) -> int:
        raw = str(text or "").strip().lower()
        if "十连" in raw:
            return 10
        if "五连" in raw:
            return 5
        if "三连" in raw:
            return 3
        if "二连" in raw or "双连" in raw:
            return 2
        if "单抽" in raw or "一抽" in raw:
            return 1
        match = re.search(r"(\d{1,2})\s*连", raw)
        if match:
            try:
                return max(1, min(10, int(match.group(1))))
            except Exception:
                return 1
        return 1

    def _pick_recipe(
        self,
        text: str,
        ctx: Dict[str, Any],
        recipes: List[Dict[str, Any]],
        *,
        allow_cooldown: bool,
    ) -> Dict[str, Any] | None:
        settings = getattr(self, "settings", {}) or {}
        rate_limit_enabled = self._to_bool(settings.get("rate_limit_enabled", True))
        rate_limit_max = self._to_int(settings.get("rate_limit_max", 3), 3, 1, 20)
        rate_limit_window = self._to_int(
            settings.get("rate_limit_window_seconds", 60), 60, 5, 600
        )
        session_cooldown_enabled = self._to_bool(
            settings.get("session_cooldown_enabled", True)
        )
        session_cooldown_seconds = self._to_int(
            settings.get("session_cooldown_seconds", 600), 600, 10, 7200
        )

        scope_key = self._build_scope_key(ctx)
        now = time.time()
        if allow_cooldown and session_cooldown_enabled:
            cooldown_until = float(self._session_cooldown_until.get(scope_key, 0.0))
            if now < cooldown_until:
                return None

        if allow_cooldown and rate_limit_enabled:
            records = [
                ts
                for ts in self._rate_records.get(scope_key, [])
                if now - ts < rate_limit_window
            ]
            records.append(now)
            self._rate_records[scope_key] = records[-30:]
            if len(records) > rate_limit_max:
                candidates = self._rank_recipes(text, recipes, settings=settings)
                recipe = self._pick_from_ranked(candidates or recipes)
                if session_cooldown_enabled:
                    self._session_cooldown_until[scope_key] = (
                        now + session_cooldown_seconds
                    )
                return recipe

        candidates = self._rank_recipes(text, recipes, settings=settings)
        recipe = self._pick_from_ranked(candidates or recipes)
        if allow_cooldown and session_cooldown_enabled:
            self._session_cooldown_until[scope_key] = now + session_cooldown_seconds
        return recipe

    def _pick_multiple_recipes(
        self,
        text: str,
        ctx: Dict[str, Any],
        recipes: List[Dict[str, Any]],
        count: int,
    ) -> List[Dict[str, Any]]:
        settings = getattr(self, "settings", {}) or {}
        ranked = self._rank_recipes(text, recipes, settings=settings)
        pool = list(ranked[: max(120, count * 18)]) if ranked else list(recipes)
        if not pool:
            return []
        if len(pool) <= count:
            return pool
        visual_pool = [item for item in pool if self._resolve_usable_recipe_image(item)]
        if len(visual_pool) >= max(3, count // 2):
            pool = visual_pool + [item for item in pool if item not in visual_pool]

        rank_weights = {
            id(recipe): max(1, len(pool) - index) for index, recipe in enumerate(pool)
        }
        buckets = {rarity: [] for rarity in self._RARITY_ORDER}
        for recipe in pool:
            buckets[self._get_recipe_rarity(recipe)].append(recipe)

        picks: List[Dict[str, Any]] = []
        for _ in range(count):
            rarity = self._roll_gacha_rarity(buckets)
            recipe = self._draw_from_gacha_bucket(buckets, rarity, rank_weights)
            if recipe is None:
                break
            picks.append(recipe)
            self._remove_recipe_from_buckets(buckets, recipe)

        if count > 1 and not any(self._get_recipe_rarity(item) >= 4 for item in picks):
            guaranteed = self._draw_from_rarity_group(buckets, (5, 4), rank_weights)
            if guaranteed is not None:
                replace_index = self._find_lowest_rarity_index(picks)
                if replace_index >= 0:
                    picks[replace_index] = guaranteed
                else:
                    picks.append(guaranteed)

        if len(picks) < count:
            remainder = []
            for rarity in self._RARITY_ORDER:
                remainder.extend(buckets.get(rarity) or [])
            if remainder:
                missing = count - len(picks)
                picks.extend(
                    self._draw_unique_weighted(remainder, rank_weights, missing)
                )
        return picks[:count]

    def _filter_recipes(
        self, text: str, recipes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        raw = str(text or "").strip().lower()
        tags = self._infer_tags(raw)
        if not tags:
            return recipes
        filtered = []
        for recipe in recipes:
            haystack = " ".join(
                [
                    str(recipe.get("name") or "").lower(),
                    str(recipe.get("category") or "").lower(),
                    str(recipe.get("source") or "").lower(),
                    " ".join(str(item).lower() for item in (recipe.get("tags") or [])),
                ]
            )
            if all(tag in haystack for tag in tags):
                filtered.append(recipe)
        return filtered or recipes

    def _rank_recipes(
        self, text: str, recipes: List[Dict[str, Any]], *, settings: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        filtered = self._filter_recipes(text, recipes)
        if not filtered:
            return recipes
        ranked = sorted(
            filtered,
            key=lambda recipe: self._score_recipe(recipe, text, settings=settings),
            reverse=True,
        )
        return ranked

    def _score_recipe(
        self, recipe: Dict[str, Any], text: str, *, settings: Dict[str, Any]
    ) -> tuple:
        raw = str(text or "").strip().lower()
        time_slot = self._resolve_time_slot(raw, settings)
        prefer_homestyle = self._to_bool(settings.get("prefer_homestyle", True))
        prefer_complete = self._to_bool(settings.get("prefer_complete_recipe", True))
        avoid_non_homestyle = self._to_bool(
            settings.get("avoid_non_homestyle_for_eat", True)
        )

        tags = [str(item).lower() for item in (recipe.get("tags") or [])]
        title = str(recipe.get("name") or "")
        category = str(recipe.get("category") or "")
        source = str(recipe.get("source") or "")
        haystack = " ".join(
            [title.lower(), category.lower(), source.lower(), " ".join(tags)]
        )

        score = 0
        if prefer_homestyle and self._is_homestyle_recipe(recipe):
            score += 8
        if (
            avoid_non_homestyle
            and self._is_non_homestyle_recipe(recipe)
            and self._is_eat_only_text(raw)
        ):
            score -= 12
        if prefer_complete:
            score += min(len(recipe.get("steps") or []), 12)
            score += min(len(recipe.get("ingredients") or []), 8)
        if source == "HowToCook":
            score += 4

        score += self._score_time_slot_match(time_slot, haystack)
        score += self._score_lightness(raw, haystack)
        score += self._score_title_quality(title)
        score -= self._score_penalties(title, category, haystack)

        return (
            score,
            len(recipe.get("steps") or []),
            len(recipe.get("ingredients") or []),
            len(str(recipe.get("excerpt") or "")),
        )

    def _pick_from_ranked(self, recipes: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        if not recipes:
            return None
        top_n = min(5, len(recipes))
        top_candidates = recipes[:top_n]
        with_image = [
            item for item in top_candidates if self._resolve_usable_recipe_image(item)
        ]
        if with_image:
            return random.choice(with_image)
        return random.choice(top_candidates)

    def _roll_gacha_rarity(self, buckets: Dict[str, List[Dict[str, Any]]]) -> str:
        weighted = [
            (rarity, weight)
            for rarity, weight in self._GACHA_PROBABILITIES
            if buckets.get(rarity)
        ]
        if not weighted:
            for rarity in reversed(self._RARITY_ORDER):
                if buckets.get(rarity):
                    return rarity
            return ""
        total_weight = sum(weight for _, weight in weighted)
        threshold = random.random() * total_weight
        cumulative = 0.0
        for rarity, weight in weighted:
            cumulative += weight
            if threshold <= cumulative:
                return rarity
        return weighted[-1][0]

    def _draw_from_gacha_bucket(
        self,
        buckets: Dict[str, List[Dict[str, Any]]],
        rarity: str,
        rank_weights: Dict[int, int],
    ) -> Dict[str, Any] | None:
        if rarity:
            candidates = list(buckets.get(rarity) or [])
            if candidates:
                return self._draw_unique_weighted(candidates, rank_weights, 1)[0]
        for fallback_rarity in reversed(self._RARITY_ORDER):
            candidates = list(buckets.get(fallback_rarity) or [])
            if candidates:
                return self._draw_unique_weighted(candidates, rank_weights, 1)[0]
        return None

    def _draw_from_rarity_group(
        self,
        buckets: Dict[str, List[Dict[str, Any]]],
        rarities: tuple[str, ...],
        rank_weights: Dict[int, int],
    ) -> Dict[str, Any] | None:
        candidates: List[Dict[str, Any]] = []
        for rarity in rarities:
            candidates.extend(buckets.get(rarity) or [])
        if not candidates:
            return None
        picked = self._draw_unique_weighted(candidates, rank_weights, 1)[0]
        self._remove_recipe_from_buckets(buckets, picked)
        return picked

    def _draw_unique_weighted(
        self,
        candidates: List[Dict[str, Any]],
        rank_weights: Dict[int, int],
        count: int,
    ) -> List[Dict[str, Any]]:
        pool = list(candidates)
        results: List[Dict[str, Any]] = []
        while pool and len(results) < count:
            weights = [rank_weights.get(id(item), 1) for item in pool]
            picked = random.choices(pool, weights=weights, k=1)[0]
            results.append(picked)
            pool = [item for item in pool if item is not picked]
        return results

    def _remove_recipe_from_buckets(
        self, buckets: Dict[str, List[Dict[str, Any]]], recipe: Dict[str, Any]
    ) -> None:
        for rarity in self._RARITY_ORDER:
            buckets[rarity] = [
                item for item in (buckets.get(rarity) or []) if item is not recipe
            ]

    def _find_lowest_rarity_index(self, recipes: List[Dict[str, Any]]) -> int:
        if not recipes:
            return -1
        rarity_rank = {rarity: index for index, rarity in enumerate(self._RARITY_ORDER)}
        lowest_index = 0
        lowest_rank = rarity_rank.get(self._get_recipe_rarity(recipes[0]), 0)
        for index, recipe in enumerate(recipes[1:], start=1):
            current_rank = rarity_rank.get(self._get_recipe_rarity(recipe), 0)
            if current_rank < lowest_rank:
                lowest_rank = current_rank
                lowest_index = index
        return lowest_index

    def _resolve_time_slot(self, text: str, settings: Dict[str, Any]) -> str:
        if "早餐" in text or "早上" in text or "早饭" in text:
            return "早餐"
        if "午餐" in text or "中午" in text or "午饭" in text:
            return "午餐"
        if "晚餐" in text or "晚上" in text or "晚饭" in text or "夜宵" in text:
            return "晚餐"
        if not self._to_bool(settings.get("time_awareness_enabled", True)):
            return ""
        hour = datetime.now().hour
        breakfast_end = self._to_int(settings.get("breakfast_end_hour", 10), 10, 5, 12)
        lunch_end = self._to_int(settings.get("lunch_end_hour", 14), 14, 10, 17)
        dinner_end = self._to_int(settings.get("dinner_end_hour", 21), 21, 17, 23)
        if hour < breakfast_end:
            return "早餐"
        if hour < lunch_end:
            return "午餐"
        if hour < dinner_end:
            return "晚餐"
        return "夜间"

    def _score_time_slot_match(self, time_slot: str, haystack: str) -> int:
        if not time_slot:
            return 0
        if time_slot == "早餐":
            if any(hint.lower() in haystack for hint in self._BREAKFAST_HINTS):
                return 12
            if any(hint.lower() in haystack for hint in self._DINNER_HINTS):
                return -6
            return 0
        if time_slot == "午餐":
            if any(hint.lower() in haystack for hint in self._LUNCH_HINTS):
                return 10
            if any(hint.lower() in haystack for hint in self._BREAKFAST_HINTS):
                return -4
            return 2
        if time_slot == "晚餐":
            if any(hint.lower() in haystack for hint in self._DINNER_HINTS):
                return 10
            if any(hint.lower() in haystack for hint in self._BREAKFAST_HINTS):
                return -8
            return 1
        if time_slot == "夜间":
            if "面" in haystack or "粥" in haystack or "汤" in haystack:
                return 6
            if any(hint.lower() in haystack for hint in self._HEAVY_HINTS):
                return -5
        return 0

    def _score_lightness(self, text: str, haystack: str) -> int:
        if any(keyword in text for keyword in ("清淡", "轻", "清爽", "别太油")):
            if any(hint.lower() in haystack for hint in self._LIGHT_HINTS):
                return 8
            if any(hint.lower() in haystack for hint in self._HEAVY_HINTS):
                return -6
        if any(keyword in text for keyword in ("重口", "下饭", "香一点", "辣一点")):
            if any(hint.lower() in haystack for hint in self._HEAVY_HINTS):
                return 7
        return 0

    def _score_title_quality(self, title: str) -> int:
        cleaned = str(title or "").strip()
        if not cleaned:
            return -20
        score = 0
        if 2 <= len(cleaned) <= 10:
            score += 3
        if not re.search(r"[（(]", cleaned):
            score += 1
        return score

    def _score_penalties(self, title: str, category: str, haystack: str) -> int:
        score = 0
        if len(str(title or "")) > 14:
            score += 2
        if any(hint in title for hint in self._NON_HOMESTYLE_TITLE_HINTS):
            score += 8
        if category in self._NON_HOMESTYLE_CATEGORY_HINTS:
            score += 10
        if "示例" in title or "模板" in title:
            score += 20
        if "配制" in haystack or "调制" in haystack:
            score += 4
        return score

    def _is_homestyle_recipe(self, recipe: Dict[str, Any]) -> bool:
        if self._is_non_homestyle_recipe(recipe):
            return False
        title = str(recipe.get("name") or "")
        category = str(recipe.get("category") or "")
        source = str(recipe.get("source") or "")
        if source == "HowToCook":
            return True
        if category in {"早餐", "主食", "凉拌", "蒸菜", "炖菜", "煮锅", "砂锅菜"}:
            return True
        if any(
            hint in title
            for hint in ("炒", "蒸", "汤", "粥", "面", "饭", "豆腐", "鸡蛋")
        ):
            return True
        return False

    def _is_non_homestyle_recipe(self, recipe: Dict[str, Any]) -> bool:
        title = str(recipe.get("name") or "")
        category = str(recipe.get("category") or "")
        if category in self._NON_HOMESTYLE_CATEGORY_HINTS:
            return True
        return any(hint in title for hint in self._NON_HOMESTYLE_TITLE_HINTS)

    def _is_eat_only_text(self, text: str) -> bool:
        return any(keyword in text for keyword in self._EAT_ONLY_KEYWORDS)

    def _infer_tags(self, text: str) -> List[str]:
        tags: List[str] = []
        mapping = {
            "早餐": ("早餐", "早上", "早饭"),
            "午餐": ("午餐", "中午", "午饭"),
            "晚餐": ("晚餐", "晚上", "晚饭"),
            "面": ("面", "面条", "米线", "粉"),
            "饭": ("饭", "盖饭", "炒饭", "粥"),
            "汤": ("汤", "粥", "羹"),
            "辣": ("辣", "麻辣", "香辣"),
            "甜": ("甜", "甜口", "甜品"),
            "炸": ("炸", "炸物", "油炸"),
            "蒸": ("蒸",),
            "凉拌": ("凉拌", "凉菜"),
            "饮品": ("喝", "饮品", "奶茶", "豆浆"),
            "素": ("素", "青菜", "蔬菜"),
            "肉": ("肉", "荤", "鸡", "牛", "猪", "排骨"),
        }
        for tag, keywords in mapping.items():
            if any(keyword in text for keyword in keywords):
                tags.append(tag)
        return tags

    def _find_recipe_from_text(
        self, text: str, recipes: List[Dict[str, Any]]
    ) -> Dict[str, Any] | None:
        raw = self._normalize_query(text)
        if not raw:
            return None

        exact_matches = [recipe for recipe in recipes if recipe.get("name") == raw]
        if exact_matches:
            return self._pick_richer_recipe(exact_matches)

        containing = [
            recipe for recipe in recipes if str(recipe.get("name") or "") in raw
        ]
        if containing:
            containing.sort(
                key=lambda item: len(str(item.get("name") or "")), reverse=True
            )
            return self._pick_richer_recipe(containing)

        contained_by = [
            recipe for recipe in recipes if raw in str(recipe.get("name") or "")
        ]
        if contained_by:
            contained_by.sort(key=lambda item: len(str(item.get("name") or "")))
            return self._pick_richer_recipe(contained_by)
        return None

    def _pick_richer_recipe(
        self, recipes: List[Dict[str, Any]]
    ) -> Dict[str, Any] | None:
        if not recipes:
            return None
        return max(
            recipes,
            key=lambda item: (
                len(item.get("steps") or []),
                len(item.get("ingredients") or []),
                len(str(item.get("excerpt") or "")),
                1 if str(item.get("source") or "") == "HowToCook" else 0,
            ),
        )

    def _normalize_query(self, text: str) -> str:
        raw = str(text or "").strip()
        for keyword in self._RECIPE_REQUEST_KEYWORDS:
            raw = raw.replace(keyword, " ")
        raw = raw.replace("的", " ")
        raw = raw.replace("一下", " ")
        raw = raw.replace("告诉我", " ")
        raw = raw.replace("教我", " ")
        raw = raw.replace("这个菜", " ")
        raw = re.sub(r"\s+", " ", raw)
        return raw.strip()

    def _format_food_response(self, food: str) -> str:
        if not food:
            return "我一时想不到推荐什么，你自己决定吧。"
        return food

    def _build_food_reply(self, recipe: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
        text = self._format_food_response(str(recipe.get("name") or ""))
        image_path = self._resolve_usable_recipe_image(recipe)
        if not image_path:
            image_path = self._build_text_card_image(text, badge="今日推荐")
        if self._is_qq_context(ctx) and image_path:
            return {
                "__type__": "gateway_image",
                "image_path": image_path,
                "caption": text,
                "success_text": f"今天就吃：{text}",
                "fallback_text": text,
            }
        if image_path:
            return f"{text}\n图片：{image_path}"
        return text

    def _build_recipe_reply(self, recipe: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
        text = self._format_recipe(recipe)
        image_path = self._resolve_usable_recipe_image(recipe)
        if not image_path:
            image_path = self._build_text_card_image(
                str(recipe.get("name") or "这道菜"), badge="做法"
            )
        if self._is_qq_context(ctx) and image_path:
            return {
                "__type__": "gateway_image",
                "image_path": image_path,
                "caption": text,
                "send_caption_with_image": True,
                "success_text": f"已把 {recipe.get('name') or '这道菜'} 的做法发给你。",
                "fallback_text": text,
            }
        if image_path:
            return f"{text}\n图片：{image_path}"
        return text

    def _build_recipe_suggestion_reply(
        self, recipe: Dict[str, Any], ctx: Dict[str, Any]
    ) -> Any:
        text = self._format_recipe_suggestion(recipe)
        image_path = self._resolve_usable_recipe_image(recipe)
        if not image_path:
            image_path = self._build_text_card_image(
                str(recipe.get("name") or "这道菜"), badge="做点什么吃"
            )
        if self._is_qq_context(ctx) and image_path:
            return {
                "__type__": "gateway_image",
                "image_path": image_path,
                "caption": text,
                "success_text": f"已给你推荐 {recipe.get('name') or '这道菜'}。",
                "fallback_text": text,
            }
        if image_path:
            return f"{text}\n图片：{image_path}"
        return text

    def _build_gacha_reply(
        self, recipes: List[Dict[str, Any]], ctx: Dict[str, Any], count: int
    ) -> Any:
        if not recipes:
            return "这次没抽到可用菜谱。"
        summary = self._build_gacha_summary(recipes)
        lines = [f"吃什么{count}连结果：", summary]
        for idx, recipe in enumerate(recipes, start=1):
            rarity = self._get_recipe_rarity(recipe)
            lines.append(
                f"{idx}. [{self._format_rarity_text(rarity)}] {recipe.get('name') or '未知菜名'}"
            )
        caption = "\n".join(lines)
        collage_path = self._build_recipe_collage(recipes)
        if self._is_qq_context(ctx) and collage_path:
            return {
                "__type__": "gateway_image",
                "image_path": collage_path,
                "caption": caption,
                "success_text": lines[0],
                "fallback_text": caption,
            }
        if collage_path:
            return f"{caption}\n拼图：{collage_path}"
        return caption

    def _build_gacha_summary(self, recipes: List[Dict[str, Any]]) -> str:
        rarity_counts = {rarity: 0 for rarity in self._RARITY_ORDER}
        for recipe in recipes:
            rarity_counts[self._get_recipe_rarity(recipe)] += 1
        parts = []
        for rarity in reversed(self._RARITY_ORDER):
            count = rarity_counts.get(rarity, 0)
            if count:
                parts.append(f"{self._format_rarity_text(rarity)}x{count}")
        return "本次卡池：" + " / ".join(parts)

    def _format_rarity_text(self, rarity: int) -> str:
        try:
            stars = max(2, min(5, int(rarity)))
        except Exception:
            stars = 2
        return f"{stars}★"

    def _get_recipe_rarity(self, recipe: Dict[str, Any]) -> int:
        score = 0
        steps = len(recipe.get("steps") or [])
        ingredients = len(recipe.get("ingredients") or [])
        title = str(recipe.get("name") or "")
        excerpt = str(recipe.get("excerpt") or "")
        category = str(recipe.get("category") or "")
        if steps >= 10:
            score += 3
        elif steps >= 7:
            score += 2
        elif steps >= 4:
            score += 1
        if ingredients >= 10:
            score += 2
        elif ingredients >= 7:
            score += 1
        if len(excerpt) >= 120:
            score += 1
        if any(
            keyword in title
            for keyword in (
                "牛",
                "牛腩",
                "羊",
                "虾",
                "鱼",
                "蟹",
                "排骨",
                "鳗",
                "鳝",
                "肘子",
                "蹄",
                "酿",
                "扣肉",
            )
        ):
            score += 2
        if any(
            keyword in title
            for keyword in ("焗", "煲", "锅", "烤", "丸子", "狮子头", "东坡", "红烧")
        ):
            score += 1
        if any(
            keyword in title
            for keyword in (
                "白水",
                "白米粥",
                "水煮蛋",
                "煮鸡蛋",
                "炒青菜",
                "清炒青菜",
                "拍黄瓜",
                "凉拌黄瓜",
            )
        ):
            score -= 2
        if category in {"早餐", "breakfast"} and steps <= 3:
            score -= 1
        if self._is_non_homestyle_recipe(recipe):
            score -= 1
        if score >= 6:
            return 5
        if score >= 4:
            return 4
        if score >= 2:
            return 3
        return 2

    def _format_recipe_suggestion(self, recipe: Dict[str, Any]) -> str:
        name = str(recipe.get("name") or "这道菜")
        ingredients = recipe.get("ingredients") or []
        steps = recipe.get("steps") or []
        lines = [f"可以做{name}。"]
        if ingredients:
            lines.append(f"配料：{self._join_preview(ingredients, limit=6)}")
        if steps:
            lines.append("做法：")
            for idx, step in enumerate(steps[:5], start=1):
                lines.append(f"{idx}. {step}")
            if len(steps) > 5:
                lines.append("后面还有步骤，你也可以直接问这道菜怎么做。")
        return "\n".join(lines)

    def _format_recipe(self, recipe: Dict[str, Any]) -> str:
        name = str(recipe.get("name") or "这道菜")
        ingredients = recipe.get("ingredients") or []
        steps = recipe.get("steps") or []
        lines = [name]
        if recipe.get("category"):
            lines.append(f"分类：{recipe['category']}")
        if ingredients:
            lines.append(f"配料：{self._join_preview(ingredients, limit=10)}")
        if steps:
            lines.append("做法：")
            for idx, step in enumerate(steps, start=1):
                lines.append(f"{idx}. {step}")
        else:
            excerpt = str(recipe.get("excerpt") or "").strip()
            if excerpt:
                lines.append(excerpt[:400])
            else:
                lines.append("这道菜目前只有名称或配图，插件里没有整理到可用做法。")
        return "\n".join(lines)

    def _join_preview(self, items: List[str], limit: int) -> str:
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        preview = cleaned[:limit]
        text = "、".join(preview)
        if len(cleaned) > limit:
            text += "等"
        return text or "未写明"

    def _resolve_recipe_image(self, recipe: Dict[str, Any]) -> str:
        recipe_path = Path(str(recipe.get("path") or "")).resolve()
        if recipe_path.exists():
            markdown_image = self._extract_markdown_image(recipe_path)
            if markdown_image:
                return markdown_image
            sibling_image = self._find_sibling_image(recipe_path)
            if sibling_image:
                return sibling_image
        return self._find_fallback_image_by_name(
            str(recipe.get("name") or ""), recipe_path
        )

    def _resolve_usable_recipe_image(self, recipe: Dict[str, Any]) -> str:
        image_path = self._resolve_recipe_image(recipe)
        if image_path and self._is_readable_image(image_path):
            return image_path
        return ""

    def _normalize_recipe_name(self, name: str) -> str:
        raw = str(name or "").strip().lower()
        if not raw:
            return ""
        return re.sub(r"[\s\-_·•,，。!！?？:：;；'\"“”‘’()（）\\[\\]{}<>]+", "", raw)

    def _find_fallback_image_by_name(self, name: str, current_path: Path) -> str:
        recipe_name = str(name or "").strip()
        if not recipe_name:
            return ""
        normalized_name = self._normalize_recipe_name(recipe_name)
        if not normalized_name:
            return ""
        recipes = self._recipes_cache or []
        exact_matches: List[Path] = []
        fuzzy_matches: List[Path] = []
        for item in recipes:
            candidate_name = str(item.get("name") or "").strip()
            candidate_path = Path(str(item.get("path") or "")).resolve()
            if candidate_path == current_path or not candidate_path.exists():
                continue
            candidate_normalized = self._normalize_recipe_name(candidate_name)
            if not candidate_normalized:
                continue
            if candidate_name == recipe_name or candidate_normalized == normalized_name:
                exact_matches.append(candidate_path)
                continue
            if (
                normalized_name in candidate_normalized
                or candidate_normalized in normalized_name
            ):
                fuzzy_matches.append(candidate_path)
        for candidate_path in [*exact_matches, *fuzzy_matches]:
            markdown_image = self._extract_markdown_image(candidate_path)
            if markdown_image and self._is_readable_image(markdown_image):
                return markdown_image
            sibling_image = self._find_sibling_image(candidate_path)
            if sibling_image and self._is_readable_image(sibling_image):
                return sibling_image
        return ""

    def _extract_markdown_image(self, recipe_path: Path) -> str:
        try:
            content = recipe_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = recipe_path.read_text(encoding="utf-8-sig")
            except Exception:
                return ""
        except Exception:
            return ""
        match = self._MARKDOWN_IMAGE_RE.search(content)
        if not match:
            return ""
        raw_ref = str(match.group(1) or "").strip().strip('"')
        if not raw_ref:
            return ""
        candidate = (recipe_path.parent / raw_ref).resolve()
        if candidate.exists() and candidate.is_file():
            return str(candidate)
        return ""

    def _find_sibling_image(self, recipe_path: Path) -> str:
        candidates = []
        for path in recipe_path.parent.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() not in self._IMAGE_SUFFIXES:
                continue
            candidates.append(path)
        exact = [path for path in candidates if path.stem == recipe_path.stem]
        if exact:
            return str(sorted(exact)[0])
        if candidates:
            return str(sorted(candidates)[0])
        return ""

    def _build_recipe_collage(self, recipes: List[Dict[str, Any]]) -> str:
        cards = []
        for recipe in recipes:
            image_path = self._resolve_usable_recipe_image(recipe)
            card = self._render_recipe_card(recipe, image_path)
            if card is not None:
                cards.append((recipe, card))
        if not cards:
            return ""

        count = len(cards)
        if count >= 10:
            cols = 5
        else:
            cols = 2 if count <= 4 else 3
        rows = (count + cols - 1) // cols
        tile_w = 400 if cols >= 5 else 512
        tile_h = 266 if cols >= 5 else 340
        gap = 20
        header_h = 96
        width = cols * tile_w + (cols + 1) * gap
        height = rows * tile_h + (rows + 1) * gap + header_h

        canvas = Image.new("RGBA", (width, height), (255, 246, 251, 255))
        draw = ImageDraw.Draw(canvas)
        title_font = self._load_font(32)
        meta_font = self._load_font(20)
        title_color = (97, 57, 78)
        meta_color = (139, 104, 124)

        accent_bg = self._load_card_asset("favicon01.png")
        if accent_bg is not None:
            accent = self._fit_cover_image(accent_bg, width, height).resize((width, height))
            accent.putalpha(32)
            canvas.alpha_composite(accent, (0, 0))

        icon = self._load_card_asset("Ave_Mujica_icon2.png")
        if icon is not None:
            icon = icon.resize((56, 56))
            icon.putalpha(230)
            canvas.alpha_composite(icon, (gap, 20))
            title_x = gap + 72
        else:
            title_x = gap

        draw.text((title_x, 18), f"吃什么{count}连", fill=title_color, font=title_font)
        draw.text(
            (title_x, 54),
            self._build_gacha_summary([recipe for recipe, _ in cards]),
            fill=meta_color,
            font=meta_font,
        )

        for idx, (recipe, card) in enumerate(cards):
            row = idx // cols
            col = idx % cols
            x = gap + col * (tile_w + gap)
            y = header_h + gap + row * (tile_h + gap)
            if card.size != (tile_w, tile_h):
                card = card.resize((tile_w, tile_h))
            canvas.alpha_composite(card, (x, y))

        output_dir = Path(tempfile.gettempdir()) / "live2d_llm_what_to_eat"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"what_to_eat_{int(time.time() * 1000)}.png"
        canvas.convert("RGB").save(output_path, format="PNG")
        return str(output_path)

    def _load_card_asset(self, name: str) -> Image.Image | None:
        path = Path(__file__).resolve().parent / "data" / "card" / name
        if not path.exists():
            return None
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            return None

    def _build_star_badges(self, rarity: int) -> Image.Image | None:
        star_name = "star_trained.png" if rarity >= 5 else "star.png"
        star = self._load_card_asset(star_name)
        if star is None:
            return None
        size = 30 if rarity >= 5 else 28
        gap = 4
        width = rarity * size + max(0, rarity - 1) * gap
        canvas = Image.new("RGBA", (width, size), (0, 0, 0, 0))
        star = star.resize((size, size))
        for idx in range(rarity):
            canvas.alpha_composite(star, (idx * (size + gap), 0))
        return canvas

    def _draw_centered_lines(
        self,
        draw: ImageDraw.ImageDraw,
        lines: List[str],
        center_x: int,
        center_y: int,
        *,
        font: ImageFont.ImageFont,
        fill: tuple[int, int, int] = (255, 255, 255),
        stroke_fill: tuple[int, int, int] = (0, 0, 0),
        stroke_width: int = 4,
        line_gap: int = 14,
    ) -> None:
        cleaned = [str(line).strip() for line in lines if str(line).strip()]
        if not cleaned:
            return
        boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width) for line in cleaned]
        heights = [box[3] - box[1] for box in boxes]
        widths = [box[2] - box[0] for box in boxes]
        total_height = sum(heights) + max(0, len(cleaned) - 1) * line_gap
        current_y = center_y - total_height // 2
        for line, width, height in zip(cleaned, widths, heights):
            draw.text(
                (center_x - width // 2, current_y),
                line,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            current_y += height + line_gap

    def _render_recipe_card(
        self, recipe: Dict[str, Any], image_path: str = ""
    ) -> Image.Image | None:
        rarity = self._get_recipe_rarity(recipe)
        frame = self._load_card_asset(self._CARD_FRAME_FILES.get(rarity, "frame-2.png"))
        if frame is None:
            return None

        card_w, card_h = 512, 340
        frame_w, frame_h = frame.size
        offset_x = max(0, (card_w - frame_w) // 2)
        offset_y = max(0, (card_h - frame_h) // 2)

        has_real_image = bool(image_path)
        cover_path = image_path
        if not cover_path:
            cover_path = self._build_text_card_image(
                str(recipe.get("name") or "未知菜名"),
                badge=self._format_rarity_text(rarity),
            )

        try:
            with Image.open(cover_path) as img:
                cover = self._fit_cover_image(
                    img.convert("RGBA"), frame_w, frame_h
                ).convert("RGBA")
        except Exception:
            return None

        canvas = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        canvas.alpha_composite(cover, (offset_x, offset_y))

        overlay = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
        title = str(recipe.get("name") or "未知菜名").strip() or "未知菜名"
        overlay_draw = ImageDraw.Draw(overlay)
        stars = self._build_star_badges(rarity)
        if stars is not None:
            half_star = max(12, stars.size[1] // 2)
            overlay.alpha_composite(stars, (18 + half_star, 18))

        if has_real_image:
            title_font = self._load_font(25)
            display_title = self._truncate_text(title, 14)
            self._draw_centered_lines(
                overlay_draw,
                [display_title],
                frame_w // 2,
                frame_h - 42,
                font=title_font,
                fill=(255, 255, 255),
                stroke_fill=(0, 0, 0),
                stroke_width=3,
                line_gap=10,
            )

        canvas.alpha_composite(overlay, (offset_x, offset_y))
        canvas.alpha_composite(frame, (offset_x, offset_y))
        return canvas

    def _is_readable_image(self, image_path: str) -> bool:
        if not image_path:
            return False
        try:
            if self._is_lfs_pointer(image_path):
                return False
            with Image.open(image_path) as img:
                img.verify()
            return True
        except Exception:
            return False

    def _is_lfs_pointer(self, image_path: str) -> bool:
        try:
            with open(image_path, "rb") as handle:
                head = handle.read(200)
        except Exception:
            return False
        return head.startswith(b"version https://git-lfs.github.com/spec/v1")

    def _load_font(self, size: int) -> ImageFont.ImageFont:
        windir = os.environ.get("WINDIR", r"C:\Windows")
        font_dir = Path(windir) / "Fonts"
        for font_name in self._FONT_CANDIDATES:
            font_path = font_dir / font_name
            if not font_path.exists():
                continue
            try:
                return ImageFont.truetype(str(font_path), size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _build_text_card_image(self, title: str, badge: str = "") -> str:
        text = str(title or "今天吃什么").strip() or "今天吃什么"
        output_dir = Path(tempfile.gettempdir()) / "live2d_llm_what_to_eat"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"what_to_eat_card_{int(time.time() * 1000)}.jpg"

        width = 720
        height = 720
        canvas = Image.new("RGB", (width, height), (249, 243, 235))
        draw = ImageDraw.Draw(canvas)
        title_font = self._load_font(54)

        draw.rounded_rectangle(
            (32, 32, width - 32, height - 32),
            radius=28,
            fill=(255, 252, 248),
            outline=(228, 214, 202),
            width=3,
        )

        lines = self._wrap_text(text, limit=8)[:4]
        self._draw_centered_lines(
            draw,
            lines,
            width // 2,
            height // 2,
            font=title_font,
            fill=(255, 255, 255),
            stroke_fill=(0, 0, 0),
            stroke_width=3,
            line_gap=18,
        )
        canvas.save(output_path, format="JPEG", quality=92)
        return str(output_path)

    def _wrap_text(self, text: str, limit: int = 14) -> List[str]:
        raw = str(text or "").strip()
        if not raw:
            return [""]
        lines = []
        current = ""
        for ch in raw:
            current += ch
            if len(current) >= limit:
                lines.append(current)
                current = ""
        if current:
            lines.append(current)
        return lines or [raw]

    def _truncate_text(self, text: str, limit: int) -> str:
        raw = str(text or "").strip()
        if len(raw) <= limit:
            return raw
        return raw[: max(1, limit - 1)] + "…"

    def _fit_cover_image(
        self, image: Image.Image, width: int, height: int
    ) -> Image.Image:
        src_w, src_h = image.size
        if src_w <= 0 or src_h <= 0:
            return image.resize((width, height))
        scale = max(width / src_w, height / src_h)
        resized = image.resize((max(1, int(src_w * scale)), max(1, int(src_h * scale))))
        left = max(0, (resized.size[0] - width) // 2)
        top = max(0, (resized.size[1] - height) // 2)
        return resized.crop((left, top, left + width, top + height))

    def _is_qq_context(self, ctx: Dict[str, Any]) -> bool:
        source = str((ctx or {}).get("source") or "").strip().lower()
        return source in {"qq_gateway", "napcat_qq"}

    def _load_recipes(self) -> List[Dict[str, Any]]:
        data_root = Path(__file__).resolve().parent / "data" / "recipes"
        if not data_root.exists():
            return []
        current_mtime = self._get_tree_mtime(data_root)
        if self._recipes_cache is not None and current_mtime <= self._recipes_mtime:
            return self._recipes_cache

        recipes: List[Dict[str, Any]] = []
        seen_keys = set()
        for path in data_root.rglob("*.md"):
            if not self._is_recipe_markdown(path):
                continue
            recipe = self._parse_recipe_markdown(path)
            if not recipe:
                continue
            dedupe_key = (
                str(recipe.get("source") or ""),
                str(recipe.get("name") or ""),
            )
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            recipes.append(recipe)

        self._recipes_cache = recipes
        self._recipes_mtime = current_mtime
        return recipes

    def _get_tree_mtime(self, root: Path) -> float:
        latest = 0.0
        for path in root.rglob("*"):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
        return latest

    def _is_recipe_markdown(self, path: Path) -> bool:
        if path.name in self._IGNORE_FILE_NAMES:
            return False
        parts = {part.lower() for part in path.parts}
        if parts & {item.lower() for item in self._IGNORE_PATH_PARTS}:
            return False
        if path.name.startswith("."):
            return False
        return True

    def _parse_recipe_markdown(self, path: Path) -> Dict[str, Any] | None:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = path.read_text(encoding="utf-8-sig")
            except Exception:
                return None
        except Exception:
            return None

        lines = [line.rstrip() for line in content.splitlines()]
        title = self._extract_title(lines, path)
        if not title:
            return None

        ingredients = self._extract_section_items(
            lines, ("必备原料和工具", "配料", "材料")
        )
        steps = self._extract_steps(lines)
        category = self._infer_category_from_path(path)
        tags = self._build_tags(path, category, title)
        excerpt = self._build_excerpt(lines)
        return {
            "name": title,
            "category": category,
            "source": self._infer_source(path),
            "ingredients": ingredients,
            "steps": steps,
            "excerpt": excerpt,
            "path": str(path),
            "tags": tags,
        }

    def _extract_title(self, lines: List[str], path: Path) -> str:
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                title = re.sub(r"的做法$", "", title)
                return title.strip()
        return path.stem.strip()

    def _extract_section_items(
        self, lines: List[str], section_names: tuple[str, ...]
    ) -> List[str]:
        items: List[str] = []
        active = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("##"):
                title = stripped.lstrip("#").strip()
                active = title in section_names
                continue
            if not active:
                continue
            if not stripped:
                continue
            if stripped.startswith("#"):
                break
            cleaned = re.sub(r"^[-*]\s*", "", stripped)
            cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned)
            if cleaned:
                items.append(cleaned)
        return items

    def _extract_steps(self, lines: List[str]) -> List[str]:
        steps = self._extract_section_items(lines, ("操作", "步骤", "做法"))
        if steps:
            return steps
        inferred: List[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("-"):
                cleaned = re.sub(r"^[-*]\s*", "", stripped)
                cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned)
                if len(cleaned) >= 4:
                    inferred.append(cleaned)
        return inferred[:12]

    def _infer_category_from_path(self, path: Path) -> str:
        parts = [part for part in path.parts if part and part not in {path.name}]
        markers = [
            "vegetable_dish",
            "meat_dish",
            "aquatic",
            "breakfast",
            "staple",
            "semi-finished",
            "soup",
            "drink",
            "dessert",
            "condiment",
            "主食",
            "早餐",
            "凉拌",
            "卤菜",
            "蒸菜",
            "炖菜",
            "煮锅",
            "炸品",
            "烤类",
            "烫菜",
            "砂锅菜",
            "饮品",
            "配料",
        ]
        for marker in reversed(markers):
            if marker in parts:
                return marker
        return path.parent.name

    def _build_tags(self, path: Path, category: str, title: str) -> List[str]:
        tags = {category, title}
        for part in path.parts:
            if part.lower().endswith(".md"):
                continue
            if len(part.strip()) <= 1:
                continue
            tags.add(part)
        meal_mappings = {
            "早餐": "早餐",
            "breakfast": "早餐",
            "主食": "午餐",
            "staple": "午餐",
            "汤": "晚餐",
            "soup": "晚餐",
            "饮品": "饮品",
            "drink": "饮品",
        }
        for key, value in meal_mappings.items():
            if key in category or key in title:
                tags.add(value)
        if any(
            hint in title
            for hint in ("粥", "豆浆", "包子", "花卷", "三明治", "烧麦", "油条", "蛋")
        ):
            tags.add("早餐")
        if any(hint in title for hint in ("面", "米线", "饭", "盖饭", "便当", "炒饭")):
            tags.add("午餐")
        if any(hint in title for hint in ("汤", "炖", "蒸", "炒", "羹", "煲")):
            tags.add("晚餐")
        if any(hint in title for hint in self._LIGHT_HINTS):
            tags.add("清淡")
        if any(hint in title for hint in self._HEAVY_HINTS):
            tags.add("重口")
        if self._is_home_style_title(title):
            tags.add("家常")
        return sorted(tag for tag in tags if str(tag).strip())

    def _is_home_style_title(self, title: str) -> bool:
        return any(
            hint in str(title or "")
            for hint in (
                "炒",
                "蒸",
                "汤",
                "粥",
                "面",
                "饭",
                "豆腐",
                "鸡蛋",
                "青菜",
                "南瓜",
                "土豆",
            )
        )

    def _build_excerpt(self, lines: List[str]) -> str:
        content = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                continue
            cleaned = re.sub(r"^[-*]\s*", "", stripped)
            cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned)
            if cleaned:
                content.append(cleaned)
            if len(content) >= 6:
                break
        return "\n".join(content)

    def _infer_source(self, path: Path) -> str:
        parts = {part.lower() for part in path.parts}
        if "how_to_cook" in parts:
            return "HowToCook"
        if "cook_like_hoc" in parts:
            return "CookLikeHOC"
        return "unknown"

    def _build_scope_key(self, ctx: Dict[str, Any]) -> str:
        channel_meta = (ctx or {}).get("channel_meta") or {}
        source = str((ctx or {}).get("source") or "local").strip().lower()
        session_id = str(
            channel_meta.get("group_id")
            or channel_meta.get("session_id")
            or source
            or "default"
        ).strip()
        return session_id or "default"

    def _to_bool(self, value: Any) -> bool:
        if isinstance(value, dict):
            value = value.get("default", False)
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    def _to_int(self, value: Any, default: int, min_val: int, max_val: int) -> int:
        if isinstance(value, dict):
            value = value.get("default", default)
        try:
            num = int(value)
        except Exception:
            num = default
        return max(min_val, min(max_val, num))
