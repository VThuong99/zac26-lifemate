"""Execute the unchanged image notebook in a new kernel and retain failure output."""
import hashlib
import json
from pathlib import Path
import time
import nbformat
from nbclient import NotebookClient


def main():
    original = Path('/code/predict_notebook.ipynb')
    notebook = nbformat.read(original, as_version=4)
    client = NotebookClient(notebook, timeout=7100, kernel_name='python3', allow_errors=False,
                            resources={'metadata': {'path': '/code'}})
    started = time.monotonic()
    receipt = {'success': False, 'source': str(original), 'source_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
               'modified_cells': False, 'independent_kernel': True}
    try:
        client.execute()
        receipt['success'] = True
    except BaseException as e:
        receipt['error'] = repr(e)
        raise
    finally:
        receipt['wall_seconds'] = time.monotonic() - started
        with open('/result/predict_notebook.executed.ipynb', 'x') as f:
            nbformat.write(notebook, f)
        with open('/result/notebook-execution.json', 'x') as f:
            json.dump(receipt, f, indent=2); f.write('\n')

if __name__ == '__main__': main()
