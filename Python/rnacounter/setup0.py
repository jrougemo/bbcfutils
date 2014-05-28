
from distutils.core import setup
from Cython.Build import cythonize
from distutils.core import setup
from distutils.extension import Extension
from Cython.Distutils import build_ext

import numpy as np

extensions = [
    Extension("rnacounter0", ["rnacounter0.pyx"],
              include_dirs=[np.get_include()],
             )
]

setup(
    name = "rnacounter0",
    cmdclass = {'build_ext':build_ext},
    ext_modules = extensions,
    #gdb_debug=True,
)
