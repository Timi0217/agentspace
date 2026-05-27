"""Create Gateway Agent Communication Tables

Revision ID: gateway_001
Revises:
Create Date: 2026-05-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'gateway_001'
down_revision = 'j8e9f0a1b2c3'  # Depends on latest existing migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enums (will be created implicitly during table creation)
    # SQLAlchemy handles enum creation automatically

    # Create gateway_agents table
    op.create_table(
        'gateway_agents',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('handle', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('avatar_url', sa.String(), nullable=True),
        sa.Column('manifest_url', sa.String(), nullable=True),
        sa.Column('webhook_url', sa.String(), nullable=False),
        sa.Column('capabilities', postgresql.JSON(), nullable=False, server_default='{}'),
        sa.Column('policy', postgresql.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.Enum('online', 'offline', 'busy', 'idle', name='agentstatus'), nullable=False, server_default='offline'),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('rate_limit_per_hour', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('current_hour_requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_hour_reset', sa.DateTime(), nullable=True),
        sa.Column('api_key_hash', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('handle', name='uq_handle')
    )
    op.create_index('idx_gateway_agents_handle', 'gateway_agents', ['handle'])
    op.create_index('idx_gateway_agents_status', 'gateway_agents', ['status'])
    op.create_index('idx_gateway_agents_created_at', 'gateway_agents', ['created_at'])

    # Create gateway_rooms table
    op.create_table(
        'gateway_rooms',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by_agent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_by_user_id', sa.String(), nullable=True),
        sa.Column('context_summary', sa.Text(), nullable=True),
        sa.Column('last_summarized_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_private', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('max_context_window', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['created_by_agent_id'], ['gateway_agents.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_rooms_created_by_agent', 'gateway_rooms', ['created_by_agent_id'])
    op.create_index('idx_rooms_created_at', 'gateway_rooms', ['created_at'])
    op.create_index('idx_rooms_is_active', 'gateway_rooms', ['is_active'])

    # Create gateway_room_participants table
    op.create_table(
        'gateway_room_participants',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('room_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.Enum('initiator', 'invited', 'observer', name='roomrole'), nullable=False, server_default='invited'),
        sa.Column('status', sa.Enum('online', 'offline', 'processing', 'away', name='participantstatus'), nullable=False, server_default='offline'),
        sa.Column('joined_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('unread_count', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['room_id'], ['gateway_rooms.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['gateway_agents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('room_id', 'agent_id', name='uq_room_participant')
    )
    op.create_index('idx_room_participants_room', 'gateway_room_participants', ['room_id'])
    op.create_index('idx_room_participants_agent', 'gateway_room_participants', ['agent_id'])

    # Create gateway_messages table
    op.create_table(
        'gateway_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('room_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('from_agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('to_agent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('intent', sa.Enum('query', 'request', 'offer', 'confirmation', 'acknowledgment', 'status_update', 'clarification', 'answer', name='messageintent'), nullable=False, server_default='query'),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('tags', postgresql.JSON(), nullable=False, server_default='[]'),
        sa.Column('status', sa.Enum('queued', 'delivered', 'acknowledged', 'processing', 'responded', 'failed', 'expired', name='messagestatus'), nullable=False, server_default='queued'),
        sa.Column('priority', sa.String(), nullable=False, server_default='normal'),
        sa.Column('requires_response', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('response_deadline', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('cost_amount', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['room_id'], ['gateway_rooms.id']),
        sa.ForeignKeyConstraint(['from_agent_id'], ['gateway_agents.id']),
        sa.ForeignKeyConstraint(['to_agent_id'], ['gateway_agents.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_messages_room', 'gateway_messages', ['room_id'])
    op.create_index('idx_messages_from_agent', 'gateway_messages', ['from_agent_id'])
    op.create_index('idx_messages_to_agent', 'gateway_messages', ['to_agent_id'])
    op.create_index('idx_messages_status', 'gateway_messages', ['status'])
    op.create_index('idx_messages_created_at', 'gateway_messages', ['created_at'])

    # Create gateway_message_queue table
    op.create_table(
        'gateway_message_queue',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('webhook_response', postgresql.JSON(), nullable=True),
        sa.Column('webhook_status_code', sa.Integer(), nullable=True),
        sa.Column('webhook_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['message_id'], ['gateway_messages.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_message_queue_message', 'gateway_message_queue', ['message_id'])
    op.create_index('idx_message_queue_next_retry', 'gateway_message_queue', ['next_retry_at'])

    # Create gateway_deferred_responses table
    op.create_table(
        'gateway_deferred_responses',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='acknowledged'),
        sa.Column('estimated_completion', sa.DateTime(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('response_intent', sa.Enum('query', 'request', 'offer', 'confirmation', 'acknowledgment', 'status_update', 'clarification', 'answer', name='messageintent'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['message_id'], ['gateway_messages.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', name='uq_deferred_message'),
        sa.UniqueConstraint('task_id', name='uq_task_id')
    )
    op.create_index('idx_deferred_responses_task', 'gateway_deferred_responses', ['task_id'])
    op.create_index('idx_deferred_responses_message', 'gateway_deferred_responses', ['message_id'])

    # Create gateway_connections table
    op.create_table(
        'gateway_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_a_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_b_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.Enum('pending', 'accepted', 'rejected', 'blocked', name='connectionstatus'), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_a_id'], ['gateway_agents.id']),
        sa.ForeignKeyConstraint(['agent_b_id'], ['gateway_agents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_a_id', 'agent_b_id', name='uq_connection')
    )
    op.create_index('idx_connections_agent_a', 'gateway_connections', ['agent_a_id'])
    op.create_index('idx_connections_agent_b', 'gateway_connections', ['agent_b_id'])
    op.create_index('idx_connections_status', 'gateway_connections', ['status'])

    # Create gateway_transcripts table
    op.create_table(
        'gateway_transcripts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('room_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('messages_json', postgresql.JSON(), nullable=False, server_default='{}'),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('key_decisions', postgresql.JSON(), nullable=False, server_default='[]'),
        sa.Column('pending_items', postgresql.JSON(), nullable=False, server_default='[]'),
        sa.Column('effectiveness_score', sa.Float(), nullable=True),
        sa.Column('collaboration_score', sa.Float(), nullable=True),
        sa.Column('output_value_score', sa.Float(), nullable=True),
        sa.Column('total_messages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['room_id'], ['gateway_rooms.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('room_id', name='uq_transcript_room')
    )
    op.create_index('idx_transcripts_room', 'gateway_transcripts', ['room_id'])

    # Create gateway_triggers table
    op.create_table(
        'gateway_triggers',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('trigger_type', sa.Enum('schedule', 'event', 'manual', name='triggertype'), nullable=False),
        sa.Column('schedule', sa.String(), nullable=True),
        sa.Column('initiator_agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('target_agent_ids', postgresql.JSON(), nullable=False, server_default='[]'),
        sa.Column('message_template', postgresql.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('max_run_count', sa.Integer(), nullable=True),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_executed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['initiator_agent_id'], ['gateway_agents.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_triggers_initiator', 'gateway_triggers', ['initiator_agent_id'])
    op.create_index('idx_triggers_type', 'gateway_triggers', ['trigger_type'])
    op.create_index('idx_triggers_active', 'gateway_triggers', ['is_active'])

    # Create gateway_trigger_executions table
    op.create_table(
        'gateway_trigger_executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('trigger_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('room_created', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('executed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['trigger_id'], ['gateway_triggers.id']),
        sa.ForeignKeyConstraint(['room_created'], ['gateway_rooms.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_trigger_executions_trigger', 'gateway_trigger_executions', ['trigger_id'])

    # Create gateway_users table
    op.create_table(
        'gateway_users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('username', sa.String(), nullable=True),
        sa.Column('twitter_handle', sa.String(), nullable=True),
        sa.Column('github_username', sa.String(), nullable=True),
        sa.Column('avatar_url', sa.String(), nullable=True),
        sa.Column('bio', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_email'),
        sa.UniqueConstraint('username', name='uq_username')
    )
    op.create_index('idx_gateway_users_email', 'gateway_users', ['email'])
    op.create_index('idx_gateway_users_username', 'gateway_users', ['username'])

    # Create gateway_user_agents table
    op.create_table(
        'gateway_user_agents',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='owner'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['gateway_users.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['gateway_agents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'agent_id', name='uq_user_agent')
    )
    op.create_index('idx_user_agents_user', 'gateway_user_agents', ['user_id'])
    op.create_index('idx_user_agents_agent', 'gateway_user_agents', ['agent_id'])

    # Create registration_tokens table for agent self-registration
    op.create_table(
        'registration_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('handle', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['gateway_users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_registration_token')
    )
    op.create_index('idx_registration_tokens_token', 'registration_tokens', ['token'])
    op.create_index('idx_registration_tokens_expires_at', 'registration_tokens', ['expires_at'])


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_index('idx_registration_tokens_expires_at', table_name='registration_tokens')
    op.drop_index('idx_registration_tokens_token', table_name='registration_tokens')
    op.drop_table('registration_tokens')

    op.drop_index('idx_user_agents_agent', table_name='gateway_user_agents')
    op.drop_index('idx_user_agents_user', table_name='gateway_user_agents')
    op.drop_table('gateway_user_agents')

    op.drop_index('idx_gateway_users_username', table_name='gateway_users')
    op.drop_index('idx_gateway_users_email', table_name='gateway_users')
    op.drop_table('gateway_users')

    op.drop_index('idx_trigger_executions_trigger', table_name='gateway_trigger_executions')
    op.drop_table('gateway_trigger_executions')

    op.drop_index('idx_triggers_active', table_name='gateway_triggers')
    op.drop_index('idx_triggers_type', table_name='gateway_triggers')
    op.drop_index('idx_triggers_initiator', table_name='gateway_triggers')
    op.drop_table('gateway_triggers')

    op.drop_index('idx_transcripts_room', table_name='gateway_transcripts')
    op.drop_table('gateway_transcripts')

    op.drop_index('idx_connections_status', table_name='gateway_connections')
    op.drop_index('idx_connections_agent_b', table_name='gateway_connections')
    op.drop_index('idx_connections_agent_a', table_name='gateway_connections')
    op.drop_table('gateway_connections')

    op.drop_index('idx_deferred_responses_message', table_name='gateway_deferred_responses')
    op.drop_index('idx_deferred_responses_task', table_name='gateway_deferred_responses')
    op.drop_table('gateway_deferred_responses')

    op.drop_index('idx_message_queue_next_retry', table_name='gateway_message_queue')
    op.drop_index('idx_message_queue_message', table_name='gateway_message_queue')
    op.drop_table('gateway_message_queue')

    op.drop_index('idx_messages_created_at', table_name='gateway_messages')
    op.drop_index('idx_messages_status', table_name='gateway_messages')
    op.drop_index('idx_messages_to_agent', table_name='gateway_messages')
    op.drop_index('idx_messages_from_agent', table_name='gateway_messages')
    op.drop_index('idx_messages_room', table_name='gateway_messages')
    op.drop_table('gateway_messages')

    op.drop_index('idx_room_participants_agent', table_name='gateway_room_participants')
    op.drop_index('idx_room_participants_room', table_name='gateway_room_participants')
    op.drop_table('gateway_room_participants')

    op.drop_index('idx_rooms_is_active', table_name='gateway_rooms')
    op.drop_index('idx_rooms_created_at', table_name='gateway_rooms')
    op.drop_index('idx_rooms_created_by_agent', table_name='gateway_rooms')
    op.drop_table('gateway_rooms')

    op.drop_index('idx_gateway_agents_created_at', table_name='gateway_agents')
    op.drop_index('idx_gateway_agents_status', table_name='gateway_agents')
    op.drop_index('idx_gateway_agents_handle', table_name='gateway_agents')
    op.drop_table('gateway_agents')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS triggertype')
    op.execute('DROP TYPE IF EXISTS connectionstatus')
    op.execute('DROP TYPE IF EXISTS participantstatus')
    op.execute('DROP TYPE IF EXISTS roomrole')
    op.execute('DROP TYPE IF EXISTS messagestatus')
    op.execute('DROP TYPE IF EXISTS messageintent')
    op.execute('DROP TYPE IF EXISTS agentstatus')
