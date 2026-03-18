"""Tests for enhanced SDK features — follows, notifications, feed sorting."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sdk" / "python"))

from rapp import Rapp


class TestSDKFollows:
    def test_follows_method_exists(self):
        r = Rapp()
        assert hasattr(r, 'follows')
        assert callable(r.follows)

    def test_followers_method_exists(self):
        r = Rapp()
        assert hasattr(r, 'followers')
        assert callable(r.followers)

    def test_following_method_exists(self):
        r = Rapp()
        assert hasattr(r, 'following')
        assert callable(r.following)


class TestSDKNotifications:
    def test_notifications_method_exists(self):
        r = Rapp()
        assert hasattr(r, 'notifications')
        assert callable(r.notifications)


class TestSDKFeedSorting:
    def test_feed_method_exists(self):
        r = Rapp()
        assert hasattr(r, 'feed')
        assert callable(r.feed)


class TestSDKSearch:
    def test_search_method_exists(self):
        r = Rapp()
        assert hasattr(r, 'search')
        assert callable(r.search)
