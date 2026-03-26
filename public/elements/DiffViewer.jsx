// DiffViewer — Azure DevOps / GitLab style code diff viewer
// Shows old_string → new_string with line numbers, red/green highlighting

const COLORS = {
  headerBg: '#161b22',
  headerBorder: '#30363d',
  addedBg: 'rgba(46, 160, 67, 0.15)',
  addedBorder: 'rgba(46, 160, 67, 0.4)',
  addedText: '#aff5b4',
  addedGutter: 'rgba(46, 160, 67, 0.25)',
  removedBg: 'rgba(248, 81, 73, 0.15)',
  removedBorder: 'rgba(248, 81, 73, 0.4)',
  removedText: '#ffa198',
  removedGutter: 'rgba(248, 81, 73, 0.25)',
  unchangedText: '#c9d1d9',
  gutterText: 'rgba(139, 148, 158, 0.6)',
  lineNumBg: 'rgba(255,255,255,0.02)',
  divider: '#21262d',
  bodyBg: '#0d1117',
  badge: {
    add: '#238636',
    del: '#da3633',
  }
};

const FONT = "'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace";

const DiffLine = ({ type, content, oldNum, newNum }) => {
  const isAdded = type === 'added';
  const isRemoved = type === 'removed';
  const prefix = isAdded ? '+' : isRemoved ? '-' : ' ';

  return (
    <div style={{
      display: 'flex',
      alignItems: 'stretch',
      backgroundColor: isAdded ? COLORS.addedBg : isRemoved ? COLORS.removedBg : 'transparent',
      borderLeft: `3px solid ${isAdded ? COLORS.addedBorder : isRemoved ? COLORS.removedBorder : 'transparent'}`,
      minHeight: '22px',
    }}>
      {/* Old line number */}
      <div style={{
        width: '48px',
        minWidth: '48px',
        textAlign: 'right',
        padding: '0 8px',
        color: COLORS.gutterText,
        backgroundColor: isRemoved ? COLORS.removedGutter : COLORS.lineNumBg,
        fontFamily: FONT,
        fontSize: '12px',
        lineHeight: '22px',
        userSelect: 'none',
        borderRight: `1px solid ${COLORS.divider}`,
      }}>
        {oldNum || ''}
      </div>
      {/* New line number */}
      <div style={{
        width: '48px',
        minWidth: '48px',
        textAlign: 'right',
        padding: '0 8px',
        color: COLORS.gutterText,
        backgroundColor: isAdded ? COLORS.addedGutter : COLORS.lineNumBg,
        fontFamily: FONT,
        fontSize: '12px',
        lineHeight: '22px',
        userSelect: 'none',
        borderRight: `1px solid ${COLORS.divider}`,
      }}>
        {newNum || ''}
      </div>
      {/* Prefix (+/-/space) */}
      <div style={{
        width: '20px',
        minWidth: '20px',
        textAlign: 'center',
        fontFamily: FONT,
        fontSize: '13px',
        lineHeight: '22px',
        color: isAdded ? COLORS.addedText : isRemoved ? COLORS.removedText : COLORS.gutterText,
        fontWeight: 600,
        userSelect: 'none',
      }}>
        {prefix}
      </div>
      {/* Content */}
      <div style={{
        flex: 1,
        fontFamily: FONT,
        fontSize: '13px',
        lineHeight: '22px',
        padding: '0 12px 0 4px',
        color: isAdded ? COLORS.addedText : isRemoved ? COLORS.removedText : COLORS.unchangedText,
        whiteSpace: 'pre',
        overflow: 'auto',
      }}>
        {content}
      </div>
    </div>
  );
};

const HunkSeparator = ({ text }) => (
  <div style={{
    display: 'flex',
    alignItems: 'center',
    backgroundColor: 'rgba(56, 139, 253, 0.1)',
    borderTop: `1px solid ${COLORS.divider}`,
    borderBottom: `1px solid ${COLORS.divider}`,
    padding: '4px 0',
  }}>
    <div style={{ width: '99px', minWidth: '99px', borderRight: `1px solid ${COLORS.divider}` }}></div>
    <div style={{
      fontFamily: FONT,
      fontSize: '12px',
      color: '#79c0ff',
      padding: '2px 12px',
      fontStyle: 'italic',
    }}>
      {text}
    </div>
  </div>
);

export default function DiffViewer() {
  const { filename, old_str, new_str, result_msg, is_new_file } = props;

  if (!old_str && !new_str) {
    return <div style={{ color: '#8b949e', padding: '12px', fontFamily: FONT }}>No diff data available.</div>;
  }

  // For new files, old is empty — all lines are additions
  const oldLines = old_str ? old_str.split('\n') : [];
  const newLines = (new_str || '').split('\n');

  // Build diff lines using a simple LCS-based approach
  const diffLines = [];
  
  // Simple diff: show removed lines then added lines with context
  // For a proper side-by-side, we compare line by line
  let oi = 0, ni = 0;
  
  // Find common prefix
  while (oi < oldLines.length && ni < newLines.length && oldLines[oi] === newLines[ni]) {
    diffLines.push({ type: 'unchanged', content: oldLines[oi], oldNum: oi + 1, newNum: ni + 1 });
    oi++; ni++;
  }

  // Find common suffix
  let oldEnd = oldLines.length - 1;
  let newEnd = newLines.length - 1;
  const suffixLines = [];
  while (oldEnd > oi - 1 && newEnd > ni - 1 && oldLines[oldEnd] === newLines[newEnd]) {
    suffixLines.unshift({ type: 'unchanged', content: oldLines[oldEnd], oldNum: oldEnd + 1, newNum: newEnd + 1 });
    oldEnd--; newEnd--;
  }

  // Everything between prefix and suffix is changed
  for (let i = oi; i <= oldEnd; i++) {
    diffLines.push({ type: 'removed', content: oldLines[i], oldNum: i + 1 });
  }
  for (let i = ni; i <= newEnd; i++) {
    diffLines.push({ type: 'added', content: newLines[i], newNum: i + 1 });
  }

  diffLines.push(...suffixLines);

  // Stats
  const additions = diffLines.filter(l => l.type === 'added').length;
  const deletions = diffLines.filter(l => l.type === 'removed').length;

  // Collapse long unchanged sections (show max 3 context lines around changes)
  const MAX_CONTEXT = 3;
  const finalLines = [];
  const changeIndices = new Set();
  diffLines.forEach((l, i) => {
    if (l.type !== 'unchanged') changeIndices.add(i);
  });
  
  let skipping = false;
  diffLines.forEach((line, i) => {
    if (line.type === 'unchanged') {
      // Check if this line is within MAX_CONTEXT of any change
      let nearChange = false;
      for (let j = Math.max(0, i - MAX_CONTEXT); j <= Math.min(diffLines.length - 1, i + MAX_CONTEXT); j++) {
        if (changeIndices.has(j)) { nearChange = true; break; }
      }
      if (nearChange || diffLines.length <= 20) {
        if (skipping) {
          finalLines.push({ type: 'separator' });
          skipping = false;
        }
        finalLines.push(line);
      } else {
        skipping = true;
      }
    } else {
      if (skipping) {
        finalLines.push({ type: 'separator' });
        skipping = false;
      }
      finalLines.push(line);
    }
  });

  // Stat bar dots
  const total = additions + deletions;
  const dots = Math.min(total, 5);
  const addDots = total > 0 ? Math.max(1, Math.round((additions / total) * dots)) : 0;
  const delDots = dots - addDots;

  return (
    <div style={{
      backgroundColor: COLORS.bodyBg,
      border: `1px solid ${COLORS.headerBorder}`,
      borderRadius: '8px',
      overflow: 'hidden',
      margin: '10px 0',
      boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
    }}>
      {/* File Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 16px',
        backgroundColor: COLORS.headerBg,
        borderBottom: `1px solid ${COLORS.headerBorder}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {/* File icon */}
          <svg width="16" height="16" viewBox="0 0 16 16" fill="#8b949e">
            <path d="M3.75 1.5a.25.25 0 00-.25.25v12.5c0 .138.112.25.25.25h8.5a.25.25 0 00.25-.25V4.664a.25.25 0 00-.073-.177l-2.914-2.914a.25.25 0 00-.177-.073H3.75zM2 1.75C2 .784 2.784 0 3.75 0h5.586c.464 0 .909.184 1.237.513l2.914 2.914c.329.328.513.773.513 1.237v9.586A1.75 1.75 0 0112.25 16h-8.5A1.75 1.75 0 012 14.25V1.75z"/>
          </svg>
          <span style={{
            fontFamily: FONT,
            fontSize: '13px',
            fontWeight: 600,
            color: '#e6edf3',
          }}>
            {filename || 'edited file'}
          </span>
          {is_new_file && (
            <span style={{
              fontFamily: FONT,
              fontSize: '10px',
              fontWeight: 700,
              color: '#fff',
              backgroundColor: COLORS.badge.add,
              padding: '2px 6px',
              borderRadius: '4px',
              letterSpacing: '0.5px',
              textTransform: 'uppercase',
            }}>
              NEW
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontFamily: FONT, fontSize: '12px', color: '#3fb950', fontWeight: 600 }}>+{additions}</span>
          <span style={{ fontFamily: FONT, fontSize: '12px', color: '#f85149', fontWeight: 600 }}>-{deletions}</span>
          {/* Activity dots */}
          <div style={{ display: 'flex', gap: '2px', marginLeft: '4px' }}>
            {Array.from({ length: addDots }).map((_, i) => (
              <div key={`a${i}`} style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: COLORS.badge.add }} />
            ))}
            {Array.from({ length: delDots }).map((_, i) => (
              <div key={`d${i}`} style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: COLORS.badge.del }} />
            ))}
          </div>
        </div>
      </div>

      {/* Result message */}
      {result_msg && (
        <div style={{
          padding: '6px 16px',
          fontSize: '12px',
          color: '#8b949e',
          backgroundColor: 'rgba(255,255,255,0.02)',
          borderBottom: `1px solid ${COLORS.divider}`,
          fontFamily: FONT,
        }}>
          ✓ {result_msg}
        </div>
      )}

      {/* Diff Body */}
      <div style={{ maxHeight: '450px', overflowY: 'auto' }}>
        {/* Column headers */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          borderBottom: `1px solid ${COLORS.divider}`,
          backgroundColor: 'rgba(255,255,255,0.02)',
          padding: '2px 0',
        }}>
          <div style={{ width: '48px', minWidth: '48px', textAlign: 'center', fontFamily: FONT, fontSize: '10px', color: COLORS.gutterText, borderRight: `1px solid ${COLORS.divider}` }}>OLD</div>
          <div style={{ width: '48px', minWidth: '48px', textAlign: 'center', fontFamily: FONT, fontSize: '10px', color: COLORS.gutterText, borderRight: `1px solid ${COLORS.divider}` }}>NEW</div>
          <div style={{ width: '20px', minWidth: '20px' }}></div>
          <div style={{ flex: 1 }}></div>
        </div>
        
        {finalLines.map((line, i) => {
          if (line.type === 'separator') {
            return <HunkSeparator key={i} text="···" />;
          }
          return <DiffLine key={i} type={line.type} content={line.content} oldNum={line.oldNum} newNum={line.newNum} />;
        })}
      </div>
    </div>
  );
}
