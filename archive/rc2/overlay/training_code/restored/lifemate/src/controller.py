"""Execute planner-proposed actions through one ToolEnv session."""


class Controller:
    def __init__(self, env):
        # The caller owns the ToolEnv lifecycle.
        # Never create or reset an environment inside Controller.
        self.env = env

    def execute(self, action: dict) -> dict:
        """Validate one action, then execute it if valid."""

        if not isinstance(action, dict):
            return {"ok": False, "error": "Action must be an object"}

        name = action.get("name")
        arguments = action.get("arguments")

        if not isinstance(name, str) or not isinstance(arguments, dict):
            return {
                "ok": False,
                "error": "Action requires a tool name and arguments object",
            }

        validation = self.env.validate(name, arguments)

        if not validation.get("ok", False):
            return validation

        return self.env.call(name, arguments)
