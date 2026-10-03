from build.render import _plain_text


def test_plain_text_decodes_feed_entities_before_rendering():
    assert _plain_text("Launch&nbsp;&nbsp; Update &amp; Review") == "Launch Update & Review"


def test_plain_text_removes_encoded_markup():
    assert _plain_text("New &lt;b&gt;lipstick&lt;/b&gt;") == "New lipstick"
