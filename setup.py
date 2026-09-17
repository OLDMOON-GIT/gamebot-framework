"""GameBot Framework — pip install -e . 로 설치.

다른 프로젝트에서:
    from core.cdp_window import CdpWindow
    from core.potion import PotionKeys
    from core.settings import load_settings, save

게임 프로필:
    from games.lineage_classic import hp_read, run_hunt
"""
from setuptools import setup, find_packages

setup(
    name="gamebot-framework",
    version="1.0.0",
    description="게임 공용 봇 프레임워크 — CDP/HP판독/물약/줍기/HUD",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "opencv-python",
        "numpy",
    ],
)
