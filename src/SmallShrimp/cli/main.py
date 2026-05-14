from rich.console import Console
import typer

app = typer.Typer(help="SmallShrimp - AI Agent")

@app.command()
def chat() -> None:
    from .chat import run_chat_loop
    import asyncio
    asyncio.run(run_chat_loop())

@app.command()
def version() -> None:
    """显示版本号。"""
    from SmallShrimp.__about__ import __version__
    typer.echo(f"SmallShrimp v{__version__}")
    
if __name__ == "__main__":
    app()