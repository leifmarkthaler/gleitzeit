import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    client = GleitzeitClient()
    
    # Check available protocols
    info = await client.api.get("/api/v1/system/info")
    print("System info:", info)
    
    # Try to directly call timer provider
    result = await client.api.post("/api/v1/tasks/submit", {
        "protocol": "timer/v1",
        "method": "timer/sleep",
        "params": {"seconds": 1}
    })
    print("Direct timer task result:", result)

if __name__ == "__main__":
    asyncio.run(main())
