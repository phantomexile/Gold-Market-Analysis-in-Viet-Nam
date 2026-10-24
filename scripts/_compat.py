"""Giữ các đường dẫn script cũ hoạt động sau khi phân nhóm theo trách nhiệm."""

from __future__ import annotations

import importlib
import runpy
import sys


def forward_script(module_name: str, target: str) -> None:
    """Chạy CLI đích hoặc dùng chung module đích khi đường dẫn cũ được import.

    ``module_name`` là ``__name__`` của file chuyển tiếp; ``target`` là tên
    package mới. Nhánh CLI giữ nguyên tham số và mã thoát. Nhánh import dùng
    cùng đối tượng module để cấu hình, mock và trạng thái không bị nhân đôi.
    """
    if module_name == "__main__":
        # Chỉ thực thi điểm chạy khi người dùng gọi script, không chạy lúc import helper.
        runpy.run_module(target, run_name="__main__")
    else:
        sys.modules[module_name] = importlib.import_module(target)
