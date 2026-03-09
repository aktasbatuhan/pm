import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPut } from "@/lib/api";
import { cn } from "@/lib/utils";
import { FileText, Save, X } from "lucide-react";
import type { KnowledgeFile } from "@/types/api";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

export function KnowledgePage() {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const queryClient = useQueryClient();

  const { data: files, isLoading } = useQuery({
    queryKey: ["knowledge"],
    queryFn: () => apiGet<KnowledgeFile[]>("/knowledge"),
  });

  const { data: fileData, isLoading: fileLoading } = useQuery({
    queryKey: ["knowledge", selectedFile],
    queryFn: () =>
      apiGet<{ path: string; content: string }>(`/knowledge/${selectedFile}`),
    enabled: !!selectedFile,
  });

  // Sync editor content when file loads
  const loadedPath = fileData?.path;
  const loadedContent = fileData?.content;
  if (loadedPath === selectedFile && loadedContent !== undefined && !dirty) {
    if (editorContent !== loadedContent) {
      setEditorContent(loadedContent);
    }
  }

  const saveMutation = useMutation({
    mutationFn: () => apiPut(`/knowledge/${selectedFile}`, { content: editorContent }),
    onSuccess: () => {
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    },
  });

  const handleSelectFile = (path: string) => {
    setSelectedFile(path);
    setDirty(false);
    setEditorContent("");
  };

  return (
    <div className="p-6 max-w-[1400px] mx-auto h-[calc(100vh-0px)] flex flex-col">
      <div className="mb-4">
        <h1 className="text-lg font-medium text-foreground">Knowledge Base</h1>
        <p className="text-xs text-muted-foreground mt-0.5">Project knowledge files used by the AI agent</p>
      </div>

      <div className="flex-1 flex gap-4 min-h-0">
        {/* File list */}
        <div className="w-64 shrink-0 border border-border rounded-md bg-card overflow-y-auto">
          {isLoading ? (
            <div className="p-3 space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-8 bg-muted rounded animate-pulse" />
              ))}
            </div>
          ) : (files || []).length === 0 ? (
            <div className="p-4 text-center">
              <p className="text-xs text-muted-foreground">No knowledge files</p>
            </div>
          ) : (
            <div className="p-1">
              {(files || []).map((file) => (
                <button
                  key={file.path}
                  onClick={() => handleSelectFile(file.path)}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-2 rounded text-left text-xs transition-colors",
                    selectedFile === file.path
                      ? "bg-primary/15 text-primary"
                      : "text-foreground hover:bg-muted"
                  )}
                >
                  <FileText size={12} className="shrink-0" />
                  <span className="truncate flex-1">{file.path}</span>
                  <span className="text-[9px] text-muted-foreground shrink-0">{formatSize(file.size)}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Editor */}
        <div className="flex-1 border border-border rounded-md bg-card flex flex-col min-w-0">
          {selectedFile ? (
            <>
              <div className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-foreground font-medium">{selectedFile}</span>
                  {dirty && <span className="text-[9px] text-warning">unsaved</span>}
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => saveMutation.mutate()}
                    disabled={!dirty || saveMutation.isPending}
                    className={cn(
                      "flex items-center gap-1 px-2 py-1 rounded text-[10px] transition-colors",
                      dirty
                        ? "bg-primary text-primary-foreground hover:bg-primary/90"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    <Save size={10} />
                    Save
                  </button>
                  <button
                    onClick={() => {
                      setSelectedFile(null);
                      setDirty(false);
                    }}
                    className="p-1 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <X size={12} />
                  </button>
                </div>
              </div>
              {fileLoading ? (
                <div className="flex-1 p-4 animate-pulse bg-muted/20" />
              ) : (
                <textarea
                  value={editorContent}
                  onChange={(e) => {
                    setEditorContent(e.target.value);
                    setDirty(true);
                  }}
                  className="flex-1 bg-transparent p-4 text-xs text-foreground font-mono resize-none focus:outline-none leading-relaxed"
                  spellCheck={false}
                />
              )}
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <p className="text-sm text-muted-foreground">Select a file to edit</p>
                <p className="text-xs text-muted-foreground/50 mt-1">Knowledge files inform the AI agent about your project</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
