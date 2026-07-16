from harness.api.downloads import attachment_content_disposition


def test_attachment_filename_is_encoded_as_header_data() -> None:
    header = attachment_content_disposition('报告"\r\nX-Evil: yes.txt')

    assert header.startswith("attachment; filename*=UTF-8''")
    assert "\r" not in header
    assert "\n" not in header
    assert '"' not in header
    assert "%E6%8A%A5%E5%91%8A" in header
