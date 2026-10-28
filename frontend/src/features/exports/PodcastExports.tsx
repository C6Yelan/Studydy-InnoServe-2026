import type { StudydyApiClient } from "../../api/client";
import type { PodcastView } from "../../api/contracts";
import { ExportControls } from "./ExportControls";

export function PodcastExports({ api, view, index, videoReady, timelineReady }: {
  api: StudydyApiClient; view: PodcastView; index: number; videoReady: boolean; timelineReady: boolean;
}) {
  const episode = view.episodes[index];
  return <ExportControls label="匯出本集" options={[
    ...(episode.audio ? [{ value: "mp3", label: "MP3 音檔" }] : []),
    ...(episode.script && (!episode.audio || videoReady || timelineReady) ? [{ value: "md", label: "逐字稿 Markdown" }] : []),
    ...(videoReady ? [{ value: "mp4", label: "MP4 影片" }] : []),
  ]} download={format => api.downloadExport(`/v1/podcasts/${view.podcast_id}/episodes/${index}/export/${format}`)} />;
}
