from PyInstaller.utils.hooks import collect_data_files

# Corpora and tokenizers come from the configured, separately prepared model tree.
datas = collect_data_files("nltk", excludes=["**/nltk_data/**"])
hiddenimports = ["nltk.chunk.named_entity"]
