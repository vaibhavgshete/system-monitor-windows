from sysmon import fmt


def test_size():
    assert fmt.size(None) == "N/A"
    assert fmt.size(0) == "0 bytes"
    assert fmt.size(999) == "999 bytes"
    assert fmt.size(1000) == "1.0 kB"
    assert fmt.size(127_500_000) == "127.5 MB"
    assert fmt.size(1_300_000_000) == "1.3 GB"
    assert fmt.size(5e18) == "5000.0 PB"


def test_rate_and_percent():
    assert fmt.rate(413_300) == "413.3 kB/s"
    assert fmt.rate(None) == "N/A"
    assert fmt.percent(19.04) == "19.0%"
    assert fmt.percent(None) == "N/A"


def test_duration():
    assert fmt.duration(60) == "1 min"
    assert fmt.duration(120) == "2 mins"
    assert fmt.duration(50) == "50 secs"
    assert fmt.duration(1) == "1 sec"
