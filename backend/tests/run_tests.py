"""Dependency-free unittest runner. Each parameter case is reported separately."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def cases(fields, values):
    def decorate(func):
        func.test_cases = [(fields.split(','), value) for value in values]
        return func
    return decorate

if __name__ == '__main__':
    import unittest
    import test_account_access, test_agents, test_catalog_and_products, test_connector_auth, test_costing, test_london_card, test_preflight_cases, test_printer_discovery, test_product_readiness, test_safety, test_shop_admin, test_tenancy
    class AgentTests(unittest.TestCase):
        pass
    for module in (test_account_access, test_agents, test_catalog_and_products, test_connector_auth, test_costing, test_london_card, test_preflight_cases, test_printer_discovery, test_product_readiness, test_safety, test_shop_admin, test_tenancy):
        for name, func in vars(module).items():
            if not name.startswith('test_') or not callable(func): continue
            rows = getattr(func, 'test_cases', None)
            if rows is None:
                setattr(AgentTests, name, lambda self, f=func: f())
            else:
                for index, (fields, value) in enumerate(rows):
                    args = (value,) if len(fields) == 1 else tuple(value)
                    setattr(AgentTests, name + '_' + str(index), lambda self, f=func, a=args: f(*a))
    unittest.main(verbosity=2)
