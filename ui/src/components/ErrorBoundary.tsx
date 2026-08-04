import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Keeps one crashing view from blanking the whole ops console during a live
 * demo. The header/nav stay mounted (this wraps only <main>), and switching
 * tabs remounts via the `resetKey` prop so a transient error clears itself.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; resetKey?: string },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // surface for the deep-dive console without taking down the app
    console.error("view error boundary caught:", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full items-center justify-center p-6">
          <div className="max-w-lg rounded border border-sev-crit/40 bg-panel p-4 text-center">
            <div className="mb-1 font-mono text-sm text-sev-crit">this view hit an error</div>
            <div className="mb-3 text-xs text-muted">
              The rest of the console is fine — switch tabs and come back, or reload.
            </div>
            <pre className="mb-3 overflow-auto rounded bg-ink p-2 text-left text-[11px] text-fgdim">
              {this.state.error.message}
            </pre>
            <button
              className="btn text-[11px]"
              onClick={() => this.setState({ error: null })}
            >
              retry view
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
