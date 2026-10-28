import { AlertIcon } from './Icons.jsx'

export function ErrorBanner({ title, message, requestId }) {
  return (
    <div className="error-message" role="alert">
      <AlertIcon />
      <div>
        <strong>{title}</strong>
        <div className="error-detail">{message}</div>
        {requestId && <div className="error-request-id">Request ID: {requestId}</div>}
      </div>
    </div>
  )
}
