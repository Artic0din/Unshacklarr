import os

# The tests point the app at temporary folders with UNSHACKLARR_DATA: a DOWNSTREAM_DATA exported in the shell would
# win over it and send their writes to a real install.
os.environ.pop("DOWNSTREAM_DATA", None)
