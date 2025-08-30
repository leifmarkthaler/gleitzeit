"""
Ultra-Simple Provider Examples

Shows how minimal provider creation can be.
"""

from .ultra_simple import (
    UltraSimpleProvider, UltraHTTPProvider, 
    method, create_llm_provider, create_rest_provider, lambda_provider
)


# Example 1: Complete LLM provider in 15 lines
class MinimalLLM(UltraHTTPProvider):
    base_url = "http://localhost:11434"
    
    @method("generate")
    async def gen(self, prompt: str):
        r = await self.post("/api/generate", {"prompt": prompt, "model": "llama3.2", "stream": False})
        return {"response": r.get("response")}


# Example 2: One-liner LLM provider creation
ollama = create_llm_provider("http://localhost:11434", "llama3.2")


# Example 3: REST API from configuration
github_api = create_rest_provider(
    "https://api.github.com",
    {
        "get_user": "GET /users/{username}",
        "list_repos": "GET /users/{username}/repos",
        "get_repo": "GET /repos/{owner}/{repo}",
        "create_issue": "POST /repos/{owner}/{repo}/issues"
    }
)


# Example 4: Lambda-style provider (for simple logic)
echo_provider = lambda_provider(
    lambda method, **params: {
        "echo": {"text": params.get("text", ""), "reversed": params.get("text", "")[::-1]},
        "ping": {"pong": True},
        "time": {"now": "2024-08-29T12:00:00Z"}
    }.get(method, {"error": f"Unknown method: {method}"})
)


# Example 5: Weather API in 10 lines
class WeatherProvider(UltraHTTPProvider):
    base_url = "https://api.openweathermap.org/data/2.5"
    
    @method("current")
    async def current(self, city: str, api_key: str):
        data = await self.get("/weather", params={"q": city, "appid": api_key})
        return {"temp": data["main"]["temp"], "description": data["weather"][0]["description"]}


# Example 6: Multi-protocol provider (handles multiple APIs)
class MultiProvider(UltraHTTPProvider):
    @method("ollama.generate")
    async def ollama_gen(self, prompt: str):
        self.base_url = "http://localhost:11434"
        return await self.post("/api/generate", {"prompt": prompt, "model": "llama3.2"})
    
    @method("openai.complete")
    async def openai_complete(self, prompt: str, api_key: str):
        self.base_url = "https://api.openai.com/v1"
        self.session.headers["Authorization"] = f"Bearer {api_key}"
        return await self.post("/completions", {"prompt": prompt, "model": "gpt-3.5-turbo"})


# Example 7: Database query provider
class DBProvider(UltraSimpleProvider):
    @method("query")
    async def query(self, sql: str, params: list = None):
        # Simulate DB query
        return {"rows": [], "affected": 0}
    
    @method("insert", "update", "delete")
    async def modify(self, table: str, data: dict = None, where: dict = None):
        return {"success": True, "affected": 1}


# Example 8: Configuration-driven provider
def provider_from_config(config: dict):
    """
    Create a provider from pure configuration.
    
    Example config:
        {
            "base_url": "https://api.example.com",
            "methods": {
                "search": {
                    "http": "GET /search",
                    "params": ["query", "limit"],
                    "transform": "results"
                },
                "submit": {
                    "http": "POST /submit",
                    "params": ["data"],
                    "headers": {"X-API-Key": "{api_key}"}
                }
            }
        }
    """
    
    class ConfigProvider(UltraHTTPProvider):
        def __init__(self):
            super().__init__(base_url=config["base_url"])
            
            for method_name, method_config in config.get("methods", {}).items():
                self._add_method(method_name, method_config)
        
        def _add_method(self, name: str, config: dict):
            http_spec = config["http"]
            
            @method(name)
            async def handler(**params):
                parts = http_spec.split()
                http_method = parts[0]
                path = parts[1]
                
                # Apply transforms
                if "transform" in config:
                    # Extract specific field from response
                    response = await getattr(self, http_method.lower())(path, data=params)
                    return response.get(config["transform"], response)
                else:
                    return await getattr(self, http_method.lower())(path, data=params)
            
            setattr(self, name, handler)
    
    return ConfigProvider()


# Example 9: The absolute minimum - 5 line provider
class TinyProvider(UltraSimpleProvider):
    @method("run")
    async def run(self, cmd: str):
        return {"output": f"Executed: {cmd}"}


# Example 10: Provider with automatic parameter validation
class ValidatedProvider(UltraSimpleProvider):
    @method("process")
    async def process(self, 
                     text: str,           # Required
                     max_length: int = 100,  # Optional with default
                     format: str = "json"):  # Optional with default
        # The ultra-simple base class automatically:
        # - Validates required parameters
        # - Applies defaults for optional parameters
        # - Raises InvalidParameterError for missing required params
        return {
            "processed": text[:max_length],
            "format": format,
            "length": len(text)
        }