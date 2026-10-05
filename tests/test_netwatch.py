"""NetworkWatch: /async/ request tracking, which tells _wait_aio whether a deferred
AI Overview can still be on its way."""
from app.netwatch import NetworkWatch

MAIN, IFRAME = "MAIN", "IFRAME"


def watch() -> NetworkWatch:
    net = NetworkWatch()
    net._main_frame = MAIN  # set by attach() from Page.getFrameTree
    return net


def request(net, rid, url, rtype, frame=MAIN):
    net._on_request({"requestId": rid, "request": {"url": url}, "type": rtype, "frameId": frame})


def test_async_requests_of_the_page_before_do_not_count_for_the_results_page():
    # Typed search: the homepage's /async/hpba finishes before the results page loads;
    # it must not make the results page's AI Overview shell look settled.
    net = watch()
    request(net, "1", "https://www.google.com/?hl=en&gl=us", "Document")
    request(net, "2", "https://www.google.com/async/hpba?yv=3", "XHR")
    net._async_ended("2")
    assert net.async_done == 1
    request(net, "3", "https://www.google.com/search?q=mobile", "Document")
    assert net.async_done == 0 and not net.async_pending


def test_a_document_in_an_iframe_does_not_reset_async_tracking():
    net = watch()
    request(net, "1", "https://www.google.com/search?q=mobile", "Document")
    request(net, "2", "https://www.google.com/async/folsrch", "XHR")
    request(net, "3", "https://www.google.com/recaptcha/frame", "Document", frame=IFRAME)
    assert net.async_pending == {"2"}
