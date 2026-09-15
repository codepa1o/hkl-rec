from __future__ import annotations

import pytest

from backend.app.live_news.content_types import ContentAcquisitionError
from backend.app.live_news.html_adapters import (
    CHINA_NEWS_ADAPTER,
    PEOPLE_ADAPTER,
    XINHUA_ADAPTER,
)


def test_xinhua_adapter_selects_detail_and_removes_related_content() -> None:
    root = XINHUA_ADAPTER.prepare(
        """
        <html><body><div class="main-left"><div id="detail">
          <p>虚构正文第一段，介绍县域产业的发展情况。</p>
          <div class="related"><p>相关新闻推荐不属于正文。</p></div>
          <p>虚构正文第二段，介绍产业链协作情况。</p>
        </div></div></body></html>
        """,
        base_url="http://www.ha.xinhuanet.com/story.html",
    )

    text = root.text_content()
    assert "虚构正文第一段" in text
    assert "虚构正文第二段" in text
    assert "相关新闻推荐" not in text


def test_people_adapter_keeps_only_article_body() -> None:
    root = PEOPLE_ADAPTER.prepare(
        """
        <html><body>
          <div id="rm_topnav">网站导航</div>
          <div class="layout rm_txt"><div class="rm_txt_con"><div id="rm_txt_zw">
            <p>虚构正文第一段，解释公共服务问题。</p>
            <div class="recommend">热门推荐</div>
            <p>虚构正文第二段，给出进一步说明。</p>
          </div></div></div>
          <footer>网站页脚</footer>
        </body></html>
        """,
        base_url="http://health.people.com.cn/story.html",
    )

    text = root.text_content()
    assert "虚构正文第一段" in text
    assert "热门推荐" not in text
    assert "网站导航" not in text
    assert "网站页脚" not in text


def test_chinanews_adapter_keeps_content_and_drops_hot_video() -> None:
    root = CHINA_NEWS_ADAPTER.prepare(
        """
        <html><body><div class="con_left"><div id="cont_1_1_2" class="content">
          <p>虚构正文第一段，记录文化交流活动。</p>
          <div class="hot_video"><p>热门视频推荐。</p></div>
          <p>虚构正文第二段，记录参与者反馈。</p>
        </div></div></body></html>
        """,
        base_url="https://www.chinanews.com.cn/story.shtml",
    )

    text = root.text_content()
    assert "虚构正文第一段" in text
    assert "热门视频推荐" not in text


def test_adapter_rejects_unknown_template() -> None:
    with pytest.raises(ContentAcquisitionError) as raised:
        XINHUA_ADAPTER.prepare(
            "<html><body><div>没有受支持的正文容器</div></body></html>",
            base_url="http://www.xinhuanet.com/story.html",
        )

    assert raised.value.code == "unsupported_template"


def test_adapter_upgrades_protocol_relative_images_and_drops_http_images() -> None:
    root = XINHUA_ADAPTER.prepare(
        """
        <html><body><div id="detail">
          <p>虚构正文第一段。</p>
          <img src="//ha.news.cn/photo.jpg" alt="安全图片">
          <img src="http://unverified.example/photo.jpg" alt="不安全图片">
          <p>虚构正文第二段。</p>
        </div></body></html>
        """,
        base_url="http://www.ha.xinhuanet.com/story.html",
    )

    assert root.xpath(".//img/@src") == ["https://ha.news.cn/photo.jpg"]
