import { EXAMPLE_QUERIES } from '../constants.js'

export function ExampleQueries({ onSelect, disabled }) {
  return (
    <div className="examples">
      <div className="examples-label">Suggested queries</div>
      <div className="example-buttons">
        {EXAMPLE_QUERIES.map((example) => (
          <button
            key={example}
            type="button"
            className="example-btn"
            onClick={() => onSelect(example)}
            disabled={disabled}
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  )
}
