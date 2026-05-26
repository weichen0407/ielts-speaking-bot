import { useState, useCallback } from 'react';
import { Mic, AlertCircle, Square, Loader2 } from 'lucide-react';

interface IeltsExamViewProps {
  onClose?: () => void;
  onExamStart?: (chatId: string) => void;
  createChat?: () => Promise<string>;
  sendMessage?: (chatId: string, content: string) => void;
}

export function IeltsExamView({ onClose, onExamStart, createChat, sendMessage }: IeltsExamViewProps) {
  const [isStarting, setIsStarting] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);

  const handleStartExam = useCallback(async (topicNumber?: string) => {
    if (isStarting) return;
    setIsStarting(true);
    setSelectedTopic(topicNumber || 'random');

    try {
      let chatId: string;
      if (createChat) {
        chatId = await createChat();
      } else {
        // Fallback: just send to default chat
        chatId = '';
      }

      const command = topicNumber
        ? `/ielts_exam ${topicNumber}`
        : '/ielts_exam random';

      if (sendMessage && chatId) {
        sendMessage(chatId, command);
      }

      onExamStart?.(chatId);
      onClose?.();
    } catch (error) {
      console.error('Failed to start exam:', error);
      setIsStarting(false);
      setSelectedTopic(null);
    }
  }, [isStarting, createChat, sendMessage, onExamStart, onClose]);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b dark:border-gray-700">
        <div className="flex items-center gap-3">
          <Mic className="w-5 h-5 text-blue-600" />
          <div>
            <h2 className="text-lg font-semibold">IELTS Speaking Exam</h2>
            <p className="text-sm text-gray-500">Practice with an AI examiner</p>
          </div>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"
          >
            <Square className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-2xl mx-auto">
          {/* Info */}
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
            <h3 className="font-medium text-blue-900 dark:text-blue-200 mb-2">About IELTS Speaking Exam</h3>
            <ul className="text-sm text-blue-800 dark:text-blue-300 space-y-1">
              <li>• <strong>Part 1:</strong> Introduction & Interview (4 questions)</li>
              <li>• <strong>Part 2:</strong> Long Turn (describe for 1-2 minutes)</li>
              <li>• <strong>Part 3:</strong> Discussion (4 questions)</li>
            </ul>
            <p className="text-sm text-blue-700 dark:text-blue-400 mt-3">
              The AI examiner will ask questions naturally. Answer to the best of your ability.
              Your responses will be analyzed for scoring after the exam.
            </p>
          </div>

          {/* Random Exam */}
          <button
            onClick={() => handleStartExam()}
            disabled={isStarting}
            className="w-full p-4 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white rounded-lg font-medium flex items-center justify-center gap-2 mb-6"
          >
            {isStarting && selectedTopic === 'random' ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <AlertCircle className="w-5 h-5" />
            )}
            {isStarting && selectedTopic === 'random' ? 'Starting...' : 'Random Topic'}
          </button>

          {/* Divider */}
          <div className="flex items-center gap-3 mb-6">
            <div className="flex-1 border-t dark:border-gray-700" />
            <span className="text-sm text-gray-500">or select a topic</span>
            <div className="flex-1 border-t dark:border-gray-700" />
          </div>

          {/* Topic Grid */}
          <div className="grid grid-cols-3 gap-3">
            {Array.from({ length: 27 }, (_, i) => {
              const topicNum = String(i + 1).padStart(2, '0');
              return (
                <button
                  key={topicNum}
                  onClick={() => handleStartExam(topicNum)}
                  disabled={isStarting}
                  className="p-3 border dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 text-center disabled:opacity-50"
                >
                  {isStarting && selectedTopic === topicNum ? (
                    <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                  ) : (
                    <span className="font-medium">{topicNum}</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
