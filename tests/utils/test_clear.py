import tempfile
from pathlib import Path
import unittest
from utils.clear import get_dir_size, clear_folder

def create_test_dir(structure, base_dir):
	"""Создаёт тестовую директорию по структуре: {filename: content} или {dirname: {}}"""
	for name, content in structure.items():
		p = Path(base_dir) / name
		if isinstance(content, dict):
			p.mkdir(parents=True, exist_ok=True)
			create_test_dir(content, p)
		else:
			p.parent.mkdir(parents=True, exist_ok=True)
			with open(p, 'w') as f:
				f.write(content)

class TestClearUtils(unittest.TestCase):
	def test_get_dir_size(self):
		with tempfile.TemporaryDirectory() as tmp:
			structure = {
				'a.txt': 'hello',
				'b.txt': 'world',
				'subdir': {
					'c.txt': '12345',
				}
			}
			create_test_dir(structure, tmp)
			size = get_dir_size(tmp)
			self.assertEqual(size, 15)

	def test_clear_folder_basic(self):
		with tempfile.TemporaryDirectory() as tmp:
			structure = {
				'keep.json': '{}',
				'del.txt': 'delete',
				'subdir': {
					'del2.txt': 'delete',
					'keep2.json': '{}',
				}
			}
			create_test_dir(structure, tmp)
			clear_folder(tmp, exclude_files=[r'.*\.json$'])
			files = {str(p.relative_to(tmp)) for p in Path(tmp).rglob('*') if p.is_file()}
			self.assertEqual(files, {'keep.json', 'subdir/keep2.json'})

	def test_clear_folder_max_size(self):
		with tempfile.TemporaryDirectory() as tmp:
			structure = {
				'a.txt': 'x'*10,
				'b.txt': 'y'*10,
			}
			create_test_dir(structure, tmp)
			clear_folder(tmp, max_size_bytes=100)
			files = [p.name for p in Path(tmp).rglob('*') if p.is_file()]
			self.assertEqual(set(files), {'a.txt', 'b.txt'})

	def test_clear_folder_nested(self):
		with tempfile.TemporaryDirectory() as tmp:
			structure = {
				'a.txt': '1',
				'sub': {
					'b.txt': '2',
					'c.json': '3',
				}
			}
			create_test_dir(structure, tmp)
			clear_folder(tmp, exclude_files=[r'.*\.json$'])
			files = {str(p.relative_to(tmp)) for p in Path(tmp).rglob('*') if p.is_file()}
			self.assertEqual(files, {'sub/c.json'})

if __name__ == '__main__':
	unittest.main()
