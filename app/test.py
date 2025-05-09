from unittest.mock import Mock

mock = Mock()
mock.side_effect = [1, 2, 3]
print(mock())  # 1
print(mock())  # 2
