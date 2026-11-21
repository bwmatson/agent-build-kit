from pkgutil import extend_path

# The worker package holds some of this package's modules.
__path__ = extend_path(__path__, __name__)
