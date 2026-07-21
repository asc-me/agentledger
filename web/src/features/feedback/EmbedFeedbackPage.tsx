import { useSearchParams } from "react-router-dom";

import { FeedbackWidget } from "./FeedbackWidget";
import { fromParams } from "./config";

/** Standalone, unauthenticated page for embedding via iframe: /embed/feedback */
export function EmbedFeedbackPage() {
  const [search] = useSearchParams();
  const config = fromParams(search);
  return (
    <div className="flex min-h-full items-center justify-center bg-transparent p-4">
      <FeedbackWidget config={config} />
    </div>
  );
}
