// TerminalOutput — VS Code-style terminal output viewer for execute tool
// Shows command, output with stderr highlighting, and exit code badge

const FONT = "'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace";

const COLORS = {
  bg: '#1a1b26',
  headerBg: '#16161e',
  border: '#2f3347',
  command: '#7aa2f7',
  prompt: '#9ece6a',
  text: '#c0caf5',
  stderr: '#f7768e',
  stderrBg: 'rgba(247, 118, 142, 0.08)',
  dimText: '#565f89',
  successBg: 'rgba(158, 206, 106, 0.15)',
  successText: '#9ece6a',
  failBg: 'rgba(247, 118, 142, 0.15)',
  failText: '#f7768e',
  scrollbar: '#2f3347',
  truncated: '#e0af68',
};

export default function TerminalOutput() {
  const { command, output, exit_code } = props;

  if (!command && !output) {
    return <div style={{ color: COLORS.dimText, padding: '12px', fontFamily: FONT }}>No output.</div>;
  }

  // Parse output lines, identify stderr and status lines
  const rawLines = (output || '').split('\n');
  const lines = [];
  let truncated = false;

  for (const line of rawLines) {
    // Skip the "[Command succeeded/failed...]" status line — we show it as a badge
    if (line.match(/^\[Command (succeeded|failed) with exit code \d+\]$/)) continue;
    if (line.match(/^\[Output was truncated/)) { truncated = true; continue; }
    if (line.trim() === '') { lines.push({ type: 'normal', text: '' }); continue; }

    if (line.startsWith('[stderr]')) {
      lines.push({ type: 'stderr', text: line.replace('[stderr] ', '') });
    } else {
      lines.push({ type: 'normal', text: line });
    }
  }

  // Remove trailing empty lines
  while (lines.length > 0 && lines[lines.length - 1].text === '') lines.pop();

  const isSuccess = exit_code === 0;
  const exitLabel = exit_code !== null && exit_code !== undefined;

  return (
    <div style={{
      backgroundColor: COLORS.bg,
      border: `1px solid ${COLORS.border}`,
      borderRadius: '8px',
      overflow: 'hidden',
      margin: '10px 0',
      boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
    }}>
      {/* Header — command */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 16px',
        backgroundColor: COLORS.headerBg,
        borderBottom: `1px solid ${COLORS.border}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, overflow: 'hidden' }}>
          {/* Terminal icon */}
          <svg width="14" height="14" viewBox="0 0 16 16" fill={COLORS.prompt} style={{ flexShrink: 0 }}>
            <path d="M0 2.75C0 1.784.784 1 1.75 1h12.5c.966 0 1.75.784 1.75 1.75v10.5A1.75 1.75 0 0114.25 15H1.75A1.75 1.75 0 010 13.25V2.75zm1.75-.25a.25.25 0 00-.25.25v10.5c0 .138.112.25.25.25h12.5a.25.25 0 00.25-.25V2.75a.25.25 0 00-.25-.25H1.75zM7.25 8a.749.749 0 01-.22.53l-2.25 2.25a.749.749 0 11-1.06-1.06L5.44 8 3.72 6.28a.749.749 0 111.06-1.06l2.25 2.25c.141.14.22.331.22.53zm1.5 1.5a.75.75 0 000 1.5h3a.75.75 0 000-1.5h-3z"/>
          </svg>
          <span style={{ color: COLORS.prompt, fontFamily: FONT, fontSize: '12px', fontWeight: 600, userSelect: 'none', flexShrink: 0 }}>$</span>
          <span style={{
            color: COLORS.command,
            fontFamily: FONT,
            fontSize: '13px',
            fontWeight: 500,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {command}
          </span>
        </div>
        {/* Exit code badge */}
        {exitLabel && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '3px 10px',
            borderRadius: '12px',
            backgroundColor: isSuccess ? COLORS.successBg : COLORS.failBg,
            flexShrink: 0,
            marginLeft: '12px',
          }}>
            <span style={{ fontSize: '11px' }}>{isSuccess ? '✓' : '✗'}</span>
            <span style={{
              fontFamily: FONT,
              fontSize: '11px',
              fontWeight: 600,
              color: isSuccess ? COLORS.successText : COLORS.failText,
            }}>
              {isSuccess ? 'success' : `exit ${exit_code}`}
            </span>
          </div>
        )}
      </div>

      {/* Output body */}
      <div style={{
        maxHeight: '400px',
        overflowY: 'auto',
        padding: '12px 0',
      }}>
        {lines.length === 0 && (
          <div style={{ color: COLORS.dimText, fontFamily: FONT, fontSize: '12px', padding: '0 16px', fontStyle: 'italic' }}>
            {'<no output>'}
          </div>
        )}
        {lines.map((line, i) => (
          <div key={i} style={{
            fontFamily: FONT,
            fontSize: '12.5px',
            lineHeight: '20px',
            padding: '0 16px',
            color: line.type === 'stderr' ? COLORS.stderr : COLORS.text,
            backgroundColor: line.type === 'stderr' ? COLORS.stderrBg : 'transparent',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}>
            {line.type === 'stderr' && (
              <span style={{ color: COLORS.stderr, opacity: 0.5, fontSize: '10px', marginRight: '6px', userSelect: 'none' }}>stderr</span>
            )}
            {line.text || '\u00A0'}
          </div>
        ))}
      </div>

      {/* Footer — truncation warning */}
      {truncated && (
        <div style={{
          padding: '6px 16px',
          borderTop: `1px solid ${COLORS.border}`,
          backgroundColor: 'rgba(224, 175, 104, 0.08)',
          fontFamily: FONT,
          fontSize: '11px',
          color: COLORS.truncated,
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}>
          <span>⚠</span> Output was truncated due to size limits
        </div>
      )}
    </div>
  );
}
