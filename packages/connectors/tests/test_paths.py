"""平台宏路径展开（paths.py）：真机 dock 扫描的根基，宏必须有回归（2026-11-11
真机验收抓到 repl 缺 return 的真 bug——离线测试全用无宏路径，门禁拦不住）。"""

from kabao_connectors.paths import expand_storage_path


def test_windows_macro_expands_to_env_value(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))  # 任意平台可测：宏展开读 os.environ
    got = expand_storage_path("%APPDATA%/Trae CN/User/globalStorage/storage.json")
    assert got is not None
    assert "%APPDATA%" not in str(got)  # 宏必须被替换，绝不留字面量/空串
    assert str(got).startswith(str(tmp_path))  # 展开进了注入的环境值


def test_unknown_macro_returns_none():
    # 宏缺失 = 平台不适用（如 mac 上没有 %APPDATA%），正常跳过不报错
    assert expand_storage_path("%TEMP_MACRO_THAT_CANNOT_EXIST%/x.json") is None


def test_plain_home_path_expands():
    got = expand_storage_path("~/.config/Trae CN/User/globalStorage/storage.json")
    assert got is not None
    assert str(got).startswith(("/home/", "/Users/", "C:\\"))  # expanduser 生效
