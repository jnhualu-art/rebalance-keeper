"""
Mock objects and helpers for unit tests.

Provides a MockKeeperHubClient that returns canned Aave V3 data
without making any network calls.
"""

from typing import Dict, Any, Optional
from src.keeperhub_client import MCPError


class MockKeeperHubClient:
    """Mock KeeperHub client for testing. Returns canned data."""

    def __init__(
        self,
        account_data: Optional[Dict[str, str]] = None,
        reserve_data: Optional[Dict] = None,
        supply_result: Optional[Dict] = None,
        repay_result: Optional[Dict] = None,
        borrow_result: Optional[Dict] = None,
        raise_on_repay: bool = False,
    ):
        self.account_data = account_data or {
            "totalCollateralBase": "0",
            "totalDebtBase": "0",
            "availableBorrowsBase": "0",
            "currentLiquidationThreshold": "0",
            "ltv": "0",
            "healthFactor": "115792089237316195423570985008687907853269984665640564039457584007913129639935",
        }
        self.reserve_data = reserve_data or {}
        self.supply_result = supply_result or {
            "success": True,
            "transactionHash": "0xabc123",
            "gasUsed": "150000",
            "transactionLink": "https://sepolia.etherscan.io/tx/0xabc123",
        }
        self.repay_result = repay_result or {
            "success": True,
            "transactionHash": "0xdef456",
            "gasUsed": "120000",
            "transactionLink": "https://sepolia.etherscan.io/tx/0xdef456",
        }
        self.borrow_result = borrow_result or {
            "success": True,
            "transactionHash": "0x789ghi",
            "gasUsed": "180000",
        }
        self.raise_on_repay = raise_on_repay
        self.calls = []  # track all calls for assertions

    def get_user_account_data(self, user: str, network: str = None) -> Dict[str, str]:
        self.calls.append(("get_user_account_data", user))
        return dict(self.account_data)

    def get_user_reserve_data(self, user: str, asset: str, network: str = None) -> Dict:
        self.calls.append(("get_user_reserve_data", user, asset))
        return dict(self.reserve_data)

    def approve(self, token: str, spender: str, amount: str, **kwargs) -> Dict:
        self.calls.append(("approve", token, spender, amount))
        return {"success": True, "transactionHash": "0xapprove123"}

    def supply(self, asset: str, amount: str, **kwargs) -> Dict:
        self.calls.append(("supply", asset, amount))
        return dict(self.supply_result)

    def borrow(self, asset: str, amount: str, **kwargs) -> Dict:
        self.calls.append(("borrow", asset, amount))
        return dict(self.borrow_result)

    def repay(self, asset: str, amount: str, **kwargs) -> Dict:
        self.calls.append(("repay", asset, amount))
        if self.raise_on_repay:
            raise MCPError("Simulated repay failure")
        return dict(self.repay_result)

    def withdraw(self, asset: str, amount: str, **kwargs) -> Dict:
        self.calls.append(("withdraw", asset, amount))
        return {"success": True, "transactionHash": "0xwithdraw123"}

    def set_collateral(self, asset: str, use_as_collateral: bool = True, **kwargs) -> Dict:
        self.calls.append(("set_collateral", asset, use_as_collateral))
        return {"success": True}


def make_account_data(
    hf: float = 999,
    collateral: str = "0",
    debt: str = "0",
    ltv: str = "0",
    lt: str = "0",
) -> Dict[str, str]:
    """Helper to create Aave V3 account data dict.

    Args:
        hf: Health factor. Use 999 for infinity (no debt).
        collateral: Total collateral in base units.
        debt: Total debt in base units.
        ltv: Loan-to-value ratio.
        lt: Liquidation threshold.
    """
    # If hf is infinity, Aave returns uint256 max
    if hf == 999 or hf == float("inf"):
        hf_str = "115792089237316195423570985008687907853269984665640564039457584007913129639935"
    else:
        hf_str = str(int(hf * 1e18))
    return {
        "totalCollateralBase": collateral,
        "totalDebtBase": debt,
        "availableBorrowsBase": "0",
        "currentLiquidationThreshold": lt,
        "ltv": ltv,
        "healthFactor": hf_str,
    }
