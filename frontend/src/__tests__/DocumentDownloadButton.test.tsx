import '@testing-library/jest-dom';
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DocumentDownloadButton } from '@/components/DocumentDownloadButton';
import { riderService } from '@/services/rider.service';

jest.mock('@/services/rider.service', () => ({ riderService: { getDocumentFile: jest.fn() } }));
const getFile = jest.mocked(riderService.getDocumentFile);
const id = '123e4567-e89b-42d3-a456-426614174000';
let click: jest.SpyInstance;
const createURL = jest.fn(() => 'blob:private-document');
const revokeURL = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createURL });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeURL });
  click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
});
afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); });

it('downloads the authorized blob with a local filename and releases its URL', async () => {
  jest.useFakeTimers();
  getFile.mockResolvedValueOnce(new Blob(['%PDF content'], { type: 'application/pdf' }));
  render(<DocumentDownloadButton documentId={id} />);
  fireEvent.click(screen.getByRole('button'));
  await act(async () => { await Promise.resolve(); });
  expect(getFile).toHaveBeenCalledWith(id, expect.any(AbortSignal));
  expect(click).toHaveBeenCalledTimes(1);
  const anchor = click.mock.instances[0] as HTMLAnchorElement;
  expect(anchor.href).toBe('blob:private-document');
  expect(anchor.download).toBe(`documento-${id}.pdf`);
  expect(document.querySelector('a')).toBeNull();
  act(() => { jest.runOnlyPendingTimers(); });
  expect(revokeURL).toHaveBeenCalledWith('blob:private-document');
});

it('prevents duplicate clicks while the same request is pending', async () => {
  getFile.mockReturnValueOnce(new Promise(() => undefined));
  const { unmount } = render(<DocumentDownloadButton documentId={id} />);
  fireEvent.click(screen.getByRole('button'));
  fireEvent.click(screen.getByRole('button'));
  expect(screen.getByRole('button')).toBeDisabled();
  expect(getFile).toHaveBeenCalledTimes(1);
  unmount();
});

it('shows a retryable error without navigating to a public file', async () => {
  getFile.mockRejectedValueOnce(new Error('Forbidden'));
  render(<DocumentDownloadButton documentId={id} />);
  fireEvent.click(screen.getByRole('button'));
  expect(await screen.findByRole('alert')).toHaveTextContent('No fue posible descargar');
  expect(screen.getByRole('button')).toBeEnabled();
  expect(createURL).not.toHaveBeenCalled();
  expect(click).not.toHaveBeenCalled();
});

it.each([new Blob([]), '<html>not a blob</html>'])('rejects an empty or malformed response', async (value) => {
  getFile.mockResolvedValueOnce(value as Blob);
  render(<DocumentDownloadButton documentId={id} />);
  fireEvent.click(screen.getByRole('button'));
  await screen.findByRole('alert');
  expect(createURL).not.toHaveBeenCalled();
});

it('aborts on unmount and ignores a response delivered afterward', async () => {
  let resolve!: (blob: Blob) => void;
  getFile.mockReturnValueOnce(new Promise<Blob>((done) => { resolve = done; }));
  const { unmount } = render(<DocumentDownloadButton documentId={id} />);
  fireEvent.click(screen.getByRole('button'));
  const signal = getFile.mock.calls[0][1];
  unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { resolve(new Blob(['private'], { type: 'application/pdf' })); });
  expect(createURL).not.toHaveBeenCalled();
});

it('aborts the previous document on prop change and permits the new download', async () => {
  getFile.mockReturnValueOnce(new Promise(() => undefined));
  const { rerender } = render(<DocumentDownloadButton documentId={id} />);
  fireEvent.click(screen.getByRole('button'));
  const previous = getFile.mock.calls[0][1];
  const next = '123e4567-e89b-42d3-a456-426614174001';
  rerender(<DocumentDownloadButton documentId={next} />);
  expect(previous?.aborted).toBe(true);
  await waitFor(() => expect(screen.getByRole('button')).toBeEnabled());
  getFile.mockRejectedValueOnce(new Error('Not available'));
  fireEvent.click(screen.getByRole('button'));
  await screen.findByRole('alert');
  expect(getFile.mock.calls[1][0]).toBe(next);
});

it('uses the displayed revision and cancels a pending request if it changes', async () => {
  getFile.mockReturnValueOnce(new Promise(() => undefined));
  const revision = 'a'.repeat(64);
  const { rerender } = render(<DocumentDownloadButton documentId={id} revision={revision} />);
  fireEvent.click(screen.getByRole('button'));
  expect(getFile).toHaveBeenCalledWith(id, expect.any(AbortSignal), revision);
  const signal = getFile.mock.calls[0][1];
  rerender(<DocumentDownloadButton documentId={id} revision={'b'.repeat(64)} />);
  expect(signal?.aborted).toBe(true);
  await waitFor(() => expect(screen.getByRole('button')).toBeEnabled());
});

it('asks to reload a changed revision instead of offering a blind retry', async () => {
  getFile.mockRejectedValueOnce(Object.assign(new Error('Changed'), { status: 409 }));
  render(<DocumentDownloadButton documentId={id} revision={'a'.repeat(64)} />);
  fireEvent.click(screen.getByRole('button'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Recarga la lista');
  expect(createURL).not.toHaveBeenCalled();
});
