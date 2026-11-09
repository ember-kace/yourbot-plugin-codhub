"""YourBot entry point; importing this module does not start the transport."""
from yourbot_sdk import Plugin

from cod_hub.app import register

plugin = Plugin()
register(plugin)

if __name__ == "__main__":
    plugin.run()
