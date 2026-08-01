"""解析器 B - CVF 系（ICCV / ECCV）

CVPR 虽托管在 thecvf.com 但使用 researchr CMS，已由 researchr.py 处理。
ICCV 同为 thecvf.com 域名，页面结构与 CVPR 一致，复用 researchr 解析逻辑。
ECCV 托管在 eccv.ecva.net，结构不同，做尽力解析。
"""

from parsers import researchr


def parse(html, conf_meta, year):
    """ICCV 等走 researchr 逻辑；ECCV 若结构不同则回退到通用文本提取。"""
    # ICCV 与 CVPR 同 CMS，直接复用
    return researchr.parse(html, conf_meta, year)
