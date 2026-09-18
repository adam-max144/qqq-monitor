"""pytest 配置: 让 `pytest` 在本仓库直接可跑(此前仓库没有 canonical 测试命令)。

跑法(本机 venv 已装 pytest/pytest-cov):
    "D:/Desktop/.venv-tools/Scripts/python.exe" -m pytest -q
    "D:/Desktop/.venv-tools/Scripts/python.exe" -m pytest -q --cov=rock_gd --cov-report=term-missing
网络用例默认跳过(加 --run-network 才跑): 单元测试必须离线可复现。
"""
import sys

collect_ignore = []


def pytest_addoption(parser):
    parser.addoption("--run-network", action="store_true", default=False,
                     help="跑需要联网的用例(默认跳过)")


def pytest_configure(config):
    config.addinivalue_line("markers", "network: 需要联网(默认跳过, 用 --run-network 开启)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip = __import__("pytest").mark.skip(reason="需要联网; 用 --run-network 开启")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "scripts"))
