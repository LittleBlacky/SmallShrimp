import typer

app = typer.Typer(help="SmallShrimp - AI Agent")

@app.command()
def chat() -> None:
    from .chat import run_chat_loop
    import asyncio
    asyncio.run(run_chat_loop())

if __name__ == "__main__":
    app()