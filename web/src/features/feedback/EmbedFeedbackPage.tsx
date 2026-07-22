import * as React from "react";
import { useSearchParams } from "react-router-dom";

import { FeedbackWidget } from "./FeedbackWidget";
import { fromParams } from "./config";

/** Standalone, unauthenticated page for embedding via iframe: /embed/feedback */
export function EmbedFeedbackPage() {
  const [search] = useSearchParams();
  const config = fromParams(search);

  // The iframe must be see-through so the themed card floats on any host page
  // (the app's dark body background would otherwise show inside the frame).
  React.useEffect(() => {
    const prev = document.body.style.background;
    document.body.style.background = "transparent";
    return () => {
      document.body.style.background = prev;
    };
  }, []);

  return (
    <div className="flex min-h-full items-center justify-center bg-transparent p-4">
      <FeedbackWidget config={config} />
    </div>
  );
}
